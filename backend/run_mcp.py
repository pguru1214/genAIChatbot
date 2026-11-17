"""Launch one TripWeave MCP server from any working directory."""
import argparse
import importlib
import logging
import os
from pathlib import Path
import sys

PORTS = {'travel': 8101, 'accommodation': 8102, 'attractions': 8103}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('server', choices=PORTS)
    parser.add_argument('--transport', choices=['stdio', 'streamable-http'], default='stdio')
    parser.add_argument('--port', type=int, help='Local HTTP port (default: 8101/8102/8103)')
    args = parser.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    os.chdir(Path(__file__).resolve().parent)
    # Provider logs may include URLs with query-string credentials. Report sanitized
    # failures through tool results and reserve stdout exclusively for MCP messages.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.CRITICAL)
    logging.getLogger('httpcore').setLevel(logging.CRITICAL)
    module = importlib.import_module(f'app.mcp_servers.{args.server}')
    server = module.create_server(host='127.0.0.1', port=args.port or PORTS[args.server],
                                  log_level='WARNING', stateless_http=True, json_response=True)
    server.run(transport=args.transport)


if __name__ == '__main__':
    main()
