import argparse
from pathlib import Path
from .workflow import Workbench
from .server import make_server

def main():
    parser=argparse.ArgumentParser(description="Visible GPT Image 2 reference retouch workbench")
    parser.add_argument("--serve",action="store_true",help="Open the local HTTP workbench")
    parser.add_argument("--port",type=int,default=8766)
    parser.add_argument("--runs",type=Path,default=Path("runs/retouch"))
    args=parser.parse_args()
    server=make_server(Workbench(args.runs),args.port)
    print(f"Reference Retouch: http://127.0.0.1:{server.server_port}",flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=="__main__":main()
