import sys
import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any

class FlowLauncher(ABC):
    def __init__(self):
        self._read_args()
        self._handle_request()

    def _read_args(self):
        if len(sys.argv) > 1:
            self.args = json.loads(sys.argv[1])
        else:
            self.args = {}

    def _handle_request(self):
        if not self.args:
            return

        method = self.args.get('method', '')
        params = self.args.get('parameters', [])

        if method == 'query':
            results = self.query(params[0] if params else '')
            print(json.dumps({"result": results}))
        elif method == 'context_menu':
            results = self.context_menu(params[0] if params else '')
            print(json.dumps({"result": results}))
        elif hasattr(self, method):
            getattr(self, method)(*params)

    @abstractmethod
    def query(self, query: str) -> List[Dict[str, Any]]:
        pass

    def context_menu(self, data: str) -> List[Dict[str, Any]]:
        return [] 