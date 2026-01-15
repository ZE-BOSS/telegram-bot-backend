"""Test message classification with user's example messages."""
import sys
import os
sys.path.append(os.path.join(os.getcwd(), "backend"))

from core.signal_parser import SignalParser

# User's example messages
test_messages = [
    # Commentary examples
    {
        "text": "Over $15,000 USD\n\nTP5 hit\n120+ pips\n\nMy analysis for the day was right, the first zone was just too early, gold is still respecting the range. I just wish price floated more so everyone could get the second entry\n\nNFP NEWS IN 5 minutes",
        "expected": "commentary"
    },
    {
        "text": "Managing risk by moving most stops from top to BE",
        "expected": "modification"
    },
    {
        "text": "I gave the signal before price reached, but you wouldnt have had much time to enter at all. I can't control how price action moves\n\nPrice dipped into the zone and out very fast - I hope some of you got in. You guys know I always aim to give signals way ahead of time",
        "expected": "commentary"
    },
    {
        "text": "TP5 HIT",
        "expected": "commentary"
    },
    {
        "text": "Cancelling sell limit orders\n\nI was expecting a tap into my zone however it's rejected beneath and went to TP5\n\nI'm analysing price action for another entry ahead of CPI news - patience is key",
        "expected": "modification"
    },
    {
        "text": "Signal get ready. This is not financial advice. Trade and manage at your own risk",
        "expected": "commentary"
    },
    # Actionable signal
    {
        "text": "Sell Gold 4605.5 – 4601.5\n\nStop Loss 4609.5\n\nTP1 4600\nTP2 4598\nTP3 4596\nTP4 Open (4594 / 4592 / 4588 / 4583)",
        "expected": "actionable_signal"
    },
    {
        "text": "I've filled the zone and have positions all at BE. As I said, I want to manage risk aggressively before CPI news in 15 minutes.\n\nWorst positions have closed for BE, best positions at the top of the zone are still open",
        "expected": "modification"
    }
]

def test_classification():
    parser = SignalParser()
    
    print("=" * 80)
    print("MESSAGE CLASSIFICATION TEST")
    print("=" * 80)
    
    correct = 0
    total = len(test_messages)
    
    for i, test in enumerate(test_messages, 1):
        print(f"\n[Test {i}/{total}]")
        print(f"Message: {test['text'][:80]}...")
        print(f"Expected: {test['expected']}")
        
        result = parser.classify_message(test['text'])
        category = result['category']
        mod_type = result.get('modification_type')
        
        print(f"Got: {category}")
        if mod_type:
            print(f"Modification Type: {mod_type}")
        
        if category == test['expected']:
            print("[PASS]")
            correct += 1
        else:
            print("[FAIL]")
    
    print("\n" + "=" * 80)
    print(f"RESULTS: {correct}/{total} correct ({correct/total*100:.1f}%)")
    print("=" * 80)

if __name__ == "__main__":
    test_classification()
