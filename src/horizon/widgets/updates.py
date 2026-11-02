from PySide6.QtCore import QUrl, Qt, QThread, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from horizon import updater
from horizon.titlebar import TitleBar
from horizon.version import current_version


class UpdateCheckWorker(QThread):
    update_available = Signal(object)  # ReleaseInfo

    def run(self) -> None:
        try:
            release = updater.fetch_latest_release()
        except Exception as exc:
            # Hors ligne, quota de l'API atteint… : rien à signaler à l'utilisateur.
            updater.log(f"Vérification des mises à jour impossible : {exc}")
            return
        if release is not None and updater.is_newer(release.version, current_version()):
            self.update_available.emit(release)


class UpdateDownloadWorker(QThread):
    progress = Signal(int, int)       # octets reçus, total
    status_changed = Signal(str)
    ready = Signal(str)               # dossier de la nouvelle version, prêt à installer
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, release: updater.ReleaseInfo, parent=None) -> None:
        super().__init__(parent)
        self._release = release
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def run(self) -> None:
        try:
            archive = updater.download_update(
                self._release, self.progress.emit, lambda: self._cancel_requested
            )
            self.status_changed.emit("Extraction de la nouvelle version…")
            staged = updater.stage_update(archive)
        except updater.UpdateCancelled:
            updater.log("Téléchargement annulé")
            self.cancelled.emit()
            return
        except Exception as exc:
            updater.log(f"Échec de la mise à jour : {exc}")
            self.failed.emit(str(exc))
            return
        self.ready.emit(str(staged))


class UpdateDialog(QDialog):
    """Annonce une nouvelle version ; la télécharge et la prépare si l'utilisateur accepte."""

    install_ready = Signal(str)  # dossier de la nouvelle version

    def __init__(self, release: updater.ReleaseInfo, parent=None) -> None:
        super().__init__(parent)
        self._release = release
        self._worker: UpdateDownloadWorker | None = None
        self.setWindowTitle("Mise à jour")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setMinimumWidth(480)

        headline = QLabel(
            f"Horizon {release.version} est disponible "
            f"(version actuelle : {current_version()})."
        )
        headline.setWordWrap(True)

        notes = QTextBrowser(self)
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes or "_Pas de notes de version._")
        notes.setMaximumHeight(240)

        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.hide()

        self._release_btn = QPushButton("Voir la release", self)
        self._release_btn.clicked.connect(self._open_release_page)
        self._update_btn = QPushButton("Mettre à jour", self)
        self._update_btn.setDefault(True)
        self._update_btn.clicked.connect(self._start_download)
        self._close_btn = QPushButton("Plus tard", self)
        self._close_btn.clicked.connect(self.reject)

        reason = updater.can_self_update(release)
        if reason is not None:
            self._status.setText(reason)
            self._update_btn.hide()
            self._close_btn.setText("Fermer")
        else:
            self._status.hide()

        buttons = QHBoxLayout()
        buttons.addWidget(self._release_btn)
        buttons.addStretch()
        buttons.addWidget(self._update_btn)
        buttons.addWidget(self._close_btn)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 16)
        content_layout.setSpacing(12)
        content_layout.addWidget(headline)
        content_layout.addWidget(notes)
        content_layout.addWidget(self._status)
        content_layout.addWidget(self._progress)
        content_layout.addLayout(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(TitleBar(self, subtitle="Mise à jour", show_min_max=False))
        layout.addWidget(content)

    def _open_release_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self._release.html_url))

    def _start_download(self) -> None:
        self._update_btn.setEnabled(False)
        self._close_btn.setText("Annuler")
        self._status.setText("Téléchargement…")
        self._status.show()
        self._progress.setValue(0)
        self._progress.show()

        self._worker = UpdateDownloadWorker(self._release, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.status_changed.connect(self._status.setText)
        self._worker.ready.connect(self._on_ready)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(super().reject)
        self._worker.start()

    def _on_progress(self, received: int, total: int) -> None:
        if total:
            self._progress.setValue(received * 100 // total)
        self._status.setText(f"Téléchargement… {received / 1_048_576:.0f} / {total / 1_048_576:.0f} Mo")

    def _on_ready(self, staged: str) -> None:
        # Annulation demandée pendant l'extraction, qui ne s'interrompt pas : on n'installe
        # pas, le dossier préparé sera effacé au prochain lancement.
        if self._worker.cancel_requested:
            super().reject()
            return
        self._progress.setValue(100)
        self._status.setText("Horizon va redémarrer sur la nouvelle version.")
        self.install_ready.emit(staged)
        self.accept()

    def _on_failed(self, message: str) -> None:
        self._progress.hide()
        self._status.setText(f"La mise à jour a échoué : {message}")
        self._update_btn.setText("Réessayer")
        self._update_btn.setEnabled(True)
        self._close_btn.setText("Plus tard")
        self._close_btn.setEnabled(True)

    def reject(self) -> None:
        # Pendant le téléchargement, « Annuler » demande l'arrêt ; le dialogue se ferme
        # quand le thread l'a pris en compte (signal cancelled).
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._close_btn.setEnabled(False)
            self._status.setText("Annulation…")
            return
        super().reject()
