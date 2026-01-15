import os
import sys
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.signal_parser import SignalParser

def test_parser():
    parser = SignalParser()
    message = "Sell Gold 4605.5 – 4601.5\n\nStop Loss 4609.5\n\nTP1 4600\nTP2 4598\nTP3 4596\nTP4 Open (4594 / 4592 / 4588 / 4583)"
    
    result = parser.parse_signal(message)
    # Remove large raw_data for clarity
    if "raw_data" in result: del result["raw_data"]
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    test_parser()
