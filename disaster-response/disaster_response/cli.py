import argparse
import json
from pathlib import Path
from .engine import plan
from .export import export_plan
from .stochastic import stress
from .predictive import train_demo


def main():
    parser = argparse.ArgumentParser(description="CivicOps synthetic disaster planning")
    parser.add_argument("command", choices=["plan","stress","train-demo"])
    parser.add_argument("--scenario",default="data/demo/scenario.json")
    parser.add_argument("--out",default="outputs")
    parser.add_argument("--pressure",type=float,default=1)
    parser.add_argument("--horizon",type=int,default=60)
    parser.add_argument("--runs",type=int,default=120)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    if args.command == "train-demo":
        result=train_demo()
        (out/"predictive_metrics.json").write_text(json.dumps(result,indent=2))
    else:
        data=json.loads(Path(args.scenario).read_text(encoding="utf-8"))
        options={"pressure":args.pressure,"horizon_minutes":args.horizon}
        if args.command == "plan":
            result=plan(data,options)
            export_plan(data,result,out)
        else:
            result=stress(data,options,runs=args.runs)
            (out/"stress.json").write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k in ["mode","assigned","unassigned","unassigned_p50","unassigned_p95","holdout_brier"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
