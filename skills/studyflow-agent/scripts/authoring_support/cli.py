from __future__ import annotations
import argparse
import json
import sys
from .paths import Workspace
from . import vocabulary,selections,governance

class Parser(argparse.ArgumentParser):
    def error(self,message):raise ValueError("ARGUMENT: "+message)


def source(value):
    if "=" not in value:raise ValueError("SOURCE_ID: use stable-id=relative-path")
    return tuple(value.split("=",1))


def parser():
    p=Parser(description="Bounded author-material helpers; never opens a learner database")
    p.add_argument("--root",required=True)
    commands=p.add_subparsers(dest="command",required=True,parser_class=Parser)
    q=commands.add_parser("query");q.add_argument("--source",action="append",type=source,required=True)
    q.add_argument("--word",action="append",default=[]);q.add_argument("--contains");q.add_argument("--browse",action="store_true");q.add_argument("--purpose",default="")
    q.add_argument("--limit",type=int,default=20);q.add_argument("--max-chars",type=int,default=16000);q.add_argument("--cursor");q.add_argument("--exclude-selections-dir")
    q=commands.add_parser("select");q.add_argument("--recipe",required=True);q.add_argument("--output",required=True)
    q=commands.add_parser("coverage");q.add_argument("--source",action="append",type=source,required=True);q.add_argument("--selections-dir",required=True)
    q=commands.add_parser("link");q.add_argument("--selection",required=True);q.add_argument("--receipt",required=True);q.add_argument("--course",required=True);q.add_argument("--content-revision",type=int,required=True)
    q=commands.add_parser("audit");q.add_argument("--config",required=True)
    return p


def execute(argv):
    args=parser().parse_args(argv);workspace=Workspace(args.root)
    handlers={"query":vocabulary.query,"select":selections.create,"coverage":selections.coverage,"link":selections.link,"audit":governance.audit}
    return handlers[args.command](workspace,args)


def main(argv=None):
    try:
        result=execute(sys.argv[1:] if argv is None else argv)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result["ok"] else 1
    except (ValueError,OSError,KeyError,TypeError) as exc:
        text=str(exc);code=text.split(":",1)[0] if isinstance(exc,ValueError) else type(exc).__name__
        print(json.dumps({"ok":False,"error":{"code":code[:100],"message":text[:500]}},ensure_ascii=False))
        return 1
