"""Print decisions and subsequent real solver receipts from a saved value-agent run."""
import argparse
import json
from pathlib import Path

from review_value_agent import decisions


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run",type=Path,help="One recorded *-value.json or value.json")
    args=parser.parse_args()
    record=json.loads(args.run.read_bytes())
    # The targeted development check is a single pass.
    record.setdefault("rep",0)
    print(f'{record["case"]} | {record["budget"]} s | {record["status"]}')
    for i,event in enumerate(decisions(record),1):
        choices=event["candidates"]
        count=len(set(choices.values()))
        print(f'{i}. L={event["lower_tick"]}, U={event["upper_tick"]} ticks | '
              f'{count} distinct selectable endpoints | chose {event["chosen"]} at tick {event["tick"]}')
        for goal in choices:
            p=event["forecasts"][goal]
            print(f'   {goal}: P(witness)={p["witness"]:.3f}, P(exclusion)={p["exclusion"]:.3f}, '
                  f'P(unresolved)={p["unresolved"]:.3f}; expected evidence gain={event["scores"][goal]:.3f}')
        print(f'   feedback: {event["receipts"]}')
    print(f'credited lower={record["lower"]}, upper={record["upper"]} seconds; wall={record["wall"]:.3f} s')


if __name__=="__main__":
    main()
