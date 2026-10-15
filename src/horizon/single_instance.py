"""Instance unique d'Horizon.

Un mutex Win32 global dit si Horizon tourne déjà ; un serveur local Qt (named pipe)
permet à une instance relancée de demander à celle déjà ouverte de se réafficher.
"""
import ctypes
import ctypes.wintypes

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# Nom global (toutes sessions Windows) : une seule instance d'Horizon, quel que soit
# le dépôt ou l'environnement virtuel depuis lequel elle est lancée.
_MUTEX_NAME = "Global\\Horizon-SingleInstance-Mutex"
_SERVER_NAME = "Horizon-SingleInstance-Activate"
_ERROR_ALREADY_EXISTS = 183
_ASFW_ANY = ctypes.wintypes.DWORD(-1 & 0xFFFFFFFF)
_ACTIVATE_MESSAGE = b"activate"

# use_last_error=True : le code d'erreur est capturé juste après CreateMutexW,
# sans qu'un autre appel Win32 puisse l'écraser.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
_kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]


def acquire_mutex() -> int | None:
    """Crée le mutex d'instance ; None si une autre instance le détient déjà."""
    handle = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        if handle:
            _kernel32.CloseHandle(handle)
        return None
    return handle


def release_mutex(handle: int) -> None:
    _kernel32.CloseHandle(handle)


def notify_running_instance() -> bool:
    """Demande à l'instance déjà ouverte de se réafficher. True si le message est parti.

    Nécessite une QApplication (QLocalSocket).
    """
    # Le processus lancé par l'utilisateur détient le droit de premier plan : on le cède
    # à l'instance existante, sinon Windows ne ferait que clignoter sa barre des tâches.
    ctypes.windll.user32.AllowSetForegroundWindow(_ASFW_ANY)

    socket = QLocalSocket()
    # Quelques essais : l'instance existante peut être encore en train de démarrer.
    for _ in range(10):
        socket.connectToServer(_SERVER_NAME)
        if socket.waitForConnected(200):
            break
        socket.abort()
    else:
        return False

    socket.write(_ACTIVATE_MESSAGE)
    socket.flush()
    # flush() écrit souvent tout d'un coup ; waitForBytesWritten renverrait alors False.
    sent = socket.bytesToWrite() == 0 or socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()
    return sent


class ActivationServer(QObject):
    """Écoute les demandes d'activation des instances relancées."""

    activationRequested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)

    def listen(self) -> bool:
        QLocalServer.removeServer(_SERVER_NAME)
        return self._server.listen(_SERVER_NAME)

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(socket.deleteLater)
            # Le message peut être déjà arrivé avant la connexion du signal.
            if socket.bytesAvailable():
                self._on_ready_read(socket)

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        if bytes(socket.readAll().data()).startswith(_ACTIVATE_MESSAGE):
            self.activationRequested.emit()
