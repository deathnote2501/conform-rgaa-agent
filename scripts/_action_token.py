"""_action_token.py — claim "1 action par run" pour skills Python.

Le token est créé par run.sh (vide). Le 1er skill qui s'exécute le supprime
(claim). Un 2e skill dans le même run trouvera le token absent → exit 99.

Hors contexte run.sh (env var absente), no-op pour permettre tests manuels.
"""
import os, sys


def claim_or_exit():
    path = os.environ.get('CONFORM_RGAA_ACTION_TOKEN')
    if not path:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        sys.stderr.write(
            f'REFUSED: action token already consumed ({path}). '
            'Une seule action par run.\n'
        )
        sys.exit(99)
