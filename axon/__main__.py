"""AXON entry point: python -m axon"""

import sys
from axon.interfaces.cli import run_cli
from axon.core import Axon


def main():
    if "--status" in sys.argv:
        axon = Axon().start()
        print(f"{axon.config.get('name')} v{axon.config.get('version')}")
        print(f"Status: {axon.state.status.value}")
        print(f"Tools: {len(axon.registry.list())}")
        axon.shutdown()
        return

    if "--web" in sys.argv or "web" in sys.argv:
        from axon.interfaces.web import run_web
        run_web()
        return

    run_cli()


if __name__ == "__main__":
    main()
