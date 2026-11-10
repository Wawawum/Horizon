"""Hook de build hatchling : embarque draw.io dans le paquet installe.

draw.war (~47 Mo) n'est pas versionne et figure dans .gitignore, que hatchling
respecte : sans ce hook, `pip install .` installe Horizon sans l'editeur de
diagrammes, meme si tools/fetch_drawio.py a deja ete lance. Le hook appelle ce
script (sans effet si l'archive attendue est deja la) puis declare l'archive
comme artefact force dans le wheel. Pour une installation editable, l'archive
est lue directement dans le depot.
"""

import importlib.util
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

ARCHIVE = "src/horizon/resources/drawio/draw.war"


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        script = Path(self.root) / "tools" / "fetch_drawio.py"
        spec = importlib.util.spec_from_file_location("fetch_drawio", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.main()  # sys.exit avec un message en cas d'echec : le build echoue
        if version != "editable":
            build_data["force_include"][str(Path(self.root) / ARCHIVE)] = "horizon/resources/drawio/draw.war"
