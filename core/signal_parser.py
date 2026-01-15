"""LLM-based signal parser for interpreting trading signals."""
import logging
import json
import re
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
import httpx

logger = logging.getLogger(__name__)

class SignalType(str, Enum):
    """Trading signal types."""
    BUY = "buy"
    SELL = "sell"
    CLOSE = "close"
    MODIFY = "modify"
    TP_UPDATE = "tp_update"
    SL_UPDATE = "sl_update"

class MessageCategory(str, Enum):
    """Message classification categories."""
    ACTIONABLE_SIGNAL = "actionable_signal"
    MODIFICATION = "modification"
    COMMENTARY = "commentary"

class ModificationType(str, Enum):
    """Types of signal modifications."""
    BREAKEVEN_MOVE = "breakeven_move"
    CANCELLATION = "cancellation"
    PARTIAL_CLOSE = "partial_close"
    STOP_ADJUSTMENT = "stop_adjustment"
    TARGET_ADJUSTMENT = "target_adjustment"
    OTHER = "other"

class SignalParser:
    """Parse trading signals using LLM interpretation."""
    
    def __init__(self, model: str = "gpt-4", api_key: Optional[str] = None):
        """Initialize signal parser with LLM."""
        self.model = model
        self.api_key = api_key
        self.use_llm = api_key is not None
        
        # Common forex/crypto pairs
        self.common_symbols = {
            'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'NZDUSD',
            'EURJPY', 'EURGBP', 'GBPJPY', 'AUDNZD', 'CADCHF', 'AUDCAD',
            'BTC', 'ETH', 'XRP', 'ADA', 'DOT', 'SOL', 'AAPL', 'GOOGL', 'MSFT',
            'XAUUSD', 'GOLD', 'XAGUSD', 'SILVER', 'USOIL', 'UKOIL', 'XTIUSD', 'XBRUSD',
            'US30', 'NAS100', 'GER30', 'DE30', 'DE40', 'SPX500', 'US500', 'HK30', 'JPN225'
        }
        
        self.symbol_map = {
            'GOLD': 'XAUUSD',
            'SILVER': 'XAGUSD',
            'OIL': 'USOIL',
            'US30': 'DJI',   # Mapped symbols depend on broker, but common defaults
            'NAS100': 'NAS100',
            'NASDAQ': 'NAS100',
            'DOW': 'US30',
        }
    
    def parse_signal(self, message_text: str) -> Dict[str, Any]:
        """
        Parse a trading signal message.
        
        Returns:
            Dict with parsed signal data including message category
        """
        try:
            # First, classify the message
            classification = self.classify_message(message_text)
            
            # Try LLM parsing first if available
            if self.use_llm:
                result = self._parse_with_llm(message_text)
            else:
                result = self._parse_with_heuristics(message_text)
            
            # Add classification to result
            result["message_category"] = classification["category"]
            result["modification_type"] = classification.get("modification_type")
            result["is_actionable"] = classification["category"] == MessageCategory.ACTIONABLE_SIGNAL.value
            
            return result
        except Exception as e:
            logger.error(f"Error parsing signal: {e}")
            return self._error_response(str(e))
    
    def classify_message(self, message_text: str) -> Dict[str, Any]:
        """
        Classify message into actionable signal, modification, or commentary.
        
        Returns:
            Dict with category and optional modification_type
        """
        normalized = message_text.lower()
        
        # Commentary patterns (check first to avoid false positives)
        commentary_patterns = [
            r'tp\d+\s*(hit|✅|reached)',  # TP hit notifications
            r'\d+\+?\s*pips',  # Pip count updates
            r'(nfp|cpi|fomc|news)\s*(in|alert)',  # News alerts
            r'my analysis',  # Analysis commentary
            r'i (hope|wish|expect)',  # Personal commentary
            r'(managing|manage)\s*risk',  # Risk management notes
            r'patience is key',  # General advice
            r'you guys know',  # Direct address
            r'(worst|best)\s*positions',  # Position commentary
            r'signal\s*(get ready|coming)',  # Signal preparation (not actual signal)
            r'this is not financial advice',  # Disclaimer
        ]
        
        for pattern in commentary_patterns:
            if re.search(pattern, normalized):
                return {
                    "category": MessageCategory.COMMENTARY.value,
                    "modification_type": None
                }
        
        # Modification patterns
        modification_patterns = {
            ModificationType.BREAKEVEN_MOVE: [
                r'\b(be|breakeven|break\s*even)\b',
                r'moving\s*(stops|sl|stop\s*loss).*\b(to\s*)?(be|breakeven)',
                r'stops?\s*(from|to)\s*(top\s*)?be',
                r'positions?\s*at\s*be',
            ],
            ModificationType.CANCELLATION: [
                r'cancel(l)?ing',
                r'cancel\s*(sell|buy)\s*(limit|stop)',
                r'delete\s*(order|pending)',
            ],
            ModificationType.PARTIAL_CLOSE: [
                r'partial(ly)?\s*(close|exit)',
                r'close\s*half',
                r'(some|few)\s*positions?\s*closed',
                r'filled\s*the\s*zone',  # Implies partial fills
            ],
            ModificationType.STOP_ADJUSTMENT: [
                r'(adjust|move|moving|trail)\s*(stop|sl)',
                r'new\s*stop',
            ],
        }
        
        for mod_type, patterns in modification_patterns.items():
            for pattern in patterns:
                if re.search(pattern, normalized):
                    return {
                        "category": MessageCategory.MODIFICATION.value,
                        "modification_type": mod_type.value
                    }
        
        # Actionable signal patterns
        # Must have: symbol + price structure + at least SL or TP
        has_symbol = self._extract_symbol(message_text) is not None
        has_prices = self._has_price_structure(message_text)
        
        if has_symbol and has_prices:
            return {
                "category": MessageCategory.ACTIONABLE_SIGNAL.value,
                "modification_type": None
            }
        
        # Default to commentary if unclear
        return {
            "category": MessageCategory.COMMENTARY.value,
            "modification_type": None
        }
    
    def _has_price_structure(self, message_text: str) -> bool:
        """Check if message has a proper price structure for trading."""
        normalized = message_text.lower()
        
        # Look for entry price patterns
        has_entry = bool(re.search(r'\d+\.?\d*\s*[-–—]\s*\d+\.?\d*', message_text))  # Range
        has_entry = has_entry or bool(re.search(r'(entry|buy|sell)\s*[@:at]?\s*\d+\.?\d+', normalized))
        
        # Look for SL/TP
        has_sl = bool(re.search(r'(sl|stop\s*loss|stoploss)\s*[@:at]?\s*\d+\.?\d+', normalized))
        has_tp = bool(re.search(r'(tp\d*|take\s*profit|target)\s*[@:at]?\s*\d+\.?\d+', normalized))
        
        return has_entry and (has_sl or has_tp)
    
    def _parse_with_llm(self, message_text: str) -> Dict[str, Any]:
        """Parse signal using LLM API."""
        try:
            prompt = self._build_parsing_prompt(message_text)
            
            # Call LLM API (example for OpenAI)
            response = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 500,
                }
            )
            
            if response.status_code != 200:
                logger.warning(f"LLM API error: {response.text}, falling back to heuristics")
                return self._parse_with_heuristics(message_text)
            
            result = response.json()
            parsed_content = result["choices"][0]["message"]["content"]
            
            # Parse LLM response
            return self._parse_llm_response(parsed_content, message_text)
            
        except Exception as e:
            logger.warning(f"LLM parsing failed: {e}, using heuristics")
            return self._parse_with_heuristics(message_text)
    
    def _parse_with_heuristics(self, message_text: str) -> Dict[str, Any]:
        """Parse signal using pattern matching and heuristics."""
        logger.info("Using heuristic-based signal parsing")
        
        # Normalize message
        normalized = message_text.lower()
        
        # Determine signal type
        signal_type = self._determine_signal_type(normalized)
        
        # Extract symbol
        symbol = self._extract_symbol(message_text)
        
        # Extract price levels
        prices = self._extract_prices(message_text)
        entry = prices.get("entry")
        stop_loss = prices.get("stop_loss")
        take_profit = prices.get("take_profit")
        
        # Calculate confidence
        confidence = self._calculate_confidence(
            signal_type, symbol, entry, stop_loss, take_profit, message_text
        )
        
        return {
            "signal_type": signal_type,
            "symbol": symbol,
            "entry_price": entry,
            "entry_range": prices.get("entry_range"),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "take_profits": prices.get("take_profits", [take_profit] if take_profit else []),
            "confidence_score": confidence,
            "parsing_method": "heuristic",
            "raw_data": {
                "normalized_message": normalized[:200],
                "symbol_confidence": 0.8 if symbol else 0.2,
            },
            "parsed_at": datetime.utcnow().isoformat(),
            "valid": signal_type is not None and symbol is not None,
        }
    
    def _build_parsing_prompt(self, message_text: str) -> str:
        """Build prompt for LLM parsing."""
        return f"""
Analyze this trading signal message and extract the following information:
1. Signal type (buy, sell, close, modify, tp_update, sl_update)
2. Trading symbol/pair (e.g., EURUSD, BTC)
3. Entry price (if specified)
4. Stop loss level (if specified)
5. Take profit target (if specified)
6. Confidence score (0-1) of your parsing accuracy
7. Any additional trading details (volume, timeframe, etc.)

Message:
{message_text}

Respond in JSON format:
{{
    "signal_type": "...",
    "symbol": "...",
    "entry_price": null or number,
    "stop_loss": null or number,
    "take_profit": null or number,
    "confidence": number between 0 and 1,
    "additional_details": {{}},
    "reasoning": "brief explanation"
}}
"""
    
    def _parse_llm_response(self, llm_response: str, original_message: str) -> Dict[str, Any]:
        """Parse LLM JSON response."""
        try:
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if not json_match:
                return self._parse_with_heuristics(original_message)
            
            parsed = json.loads(json_match.group())
            
            return {
                "signal_type": parsed.get("signal_type"),
                "symbol": parsed.get("symbol"),
                "entry_price": parsed.get("entry_price"),
                "stop_loss": parsed.get("stop_loss"),
                "take_profit": parsed.get("take_profit"),
                "confidence_score": parsed.get("confidence", 0.5),
                "parsing_method": "llm",
                "raw_data": {
                    "llm_reasoning": parsed.get("reasoning", ""),
                    "additional_details": parsed.get("additional_details", {}),
                },
                "parsed_at": datetime.utcnow().isoformat(),
                "valid": parsed.get("signal_type") is not None and parsed.get("symbol") is not None,
            }
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            return self._parse_with_heuristics(original_message)
    
    def _determine_signal_type(self, normalized_message: str) -> Optional[str]:
        """Determine signal type from message."""
        
        # Buy signals
        if any(word in normalized_message for word in 
               ["buy", "long", "entrada", "compra", "go long", "bullish", "upside", "buy stop", "buy limit"]):
            return SignalType.BUY.value
        
        # Sell signals
        if any(word in normalized_message for word in 
               ["sell", "short", "salida", "venta", "go short", "bearish", "downside", "sell stop", "sell limit"]):
            return SignalType.SELL.value
        
        # Close signals
        if any(word in normalized_message for word in 
               ["close", "cierre", "cancelar", "exit", "liquidate"]):
            return SignalType.CLOSE.value
        
        # TP update
        if any(word in normalized_message for word in 
               ["tp update", "take profit update", "target update", "nuevo tp"]):
            return SignalType.TP_UPDATE.value
        
        # SL update
        if any(word in normalized_message for word in 
               ["sl update", "stop loss update", "nuevo sl", "stoploss update"]):
            return SignalType.SL_UPDATE.value
        
        # Modify signals
        if any(word in normalized_message for word in 
               ["modify", "update", "change", "adjust", "modify position"]):
            return SignalType.MODIFY.value
        
        return None
    
    def _extract_symbol(self, message_text: str) -> Optional[str]:
        """Extract trading symbol from message."""
        message_upper = message_text.upper()
        
        # Try exact matches first
        for symbol in self.common_symbols:
            if symbol in message_upper:
                # Return mapped symbol if exists, else the symbol itself
                return self.symbol_map.get(symbol, symbol)
        
        # Try regex patterns for forex pairs (e.g., EUR/USD, EURUSD)
        forex_match = re.search(r'\b([A-Z]{3})[/\s]?([A-Z]{3})\b', message_upper)
        if forex_match:
            symbol = forex_match.group(1) + forex_match.group(2)
            return symbol
        
        # Try crypto patterns
        crypto_match = re.search(r'\b(BTC|ETH|XRP|ADA|SOL)\b', message_upper)
        if crypto_match:
            return crypto_match.group(1)
        
        # Try stock patterns
        stock_match = re.search(r'\b([A-Z]{1,5})\b\s*(stock|share)', message_upper)
        if stock_match:
            return stock_match.group(1)
        
        return None
    
    def _extract_prices(self, message_text: str) -> Dict[str, Any]:
        """Extract price levels from message with better context awareness."""
        prices = {
            "entry": None,
            "entry_range": [],
            "stop_loss": None,
            "take_profit": None,
            "take_profits": [],
        }
        
        message_lower = message_text.lower()
        # More robust price pattern: numbers with 1-7 digits and optional decimals, must have boundaries
        price_pattern = r'\b\d{1,7}(?:\.\d{1,5})?\b'
        
        # 1. Look for Entry Price / Range
        # Try range first: 2030 - 2035 or 2030 / 2035
        # Range can be prefixed by keywords or be standalone if it fits the pattern
        range_pattern = r'(?:entry|enter|entrada|@|at|price|buy|sell)?[:\s]*(' + price_pattern + r')\s*(?:-|–|—|to|/)\s*(' + price_pattern + r')'
        match = re.search(range_pattern, message_lower)
        if match:
            try:
                p1, p2 = float(match.group(1)), float(match.group(2))
                # Validity check: prices should be relatively close for a range
                if 0.5 < (p1 / p2) < 2.0:
                    prices["entry_range"] = [min(p1, p2), max(p1, p2)]
                    prices["entry"] = prices["entry_range"][0]
            except (ValueError, IndexError):
                pass

        if not prices["entry"]:
            # Try single entry
            entry_patterns = [
                r'(?:entry|enter|entrada|open|initial|@|at|price)[:\s]*(' + price_pattern + r')',
                r'(?:buy|sell)\s+(?:gold|silver|oil|us30|nas100|eurusd|gbpusd|[\w/]+)?\s*(' + price_pattern + r')'
            ]
            for pattern in entry_patterns:
                match = re.search(pattern, message_lower)
                if match:
                    prices["entry"] = float(match.group(1))
                    break
        
        # 2. Look for Stop Loss
        sl_patterns = [
            r'(?:sl|stop loss|stoploss|stop|risk)[:\s]*(' + price_pattern + r')',
        ]
        for pattern in sl_patterns:
            match = re.search(pattern, message_lower)
            if match:
                prices["stop_loss"] = float(match.group(1))
                break
                
        # 3. Look for Multiple Take Profits
        # Specifically look for TP labels followed by prices
        # regex to match TP1, TP2, Target 1, etc., including optional text like "Open" or "at"
        tp_label_pattern = r'(?:tp|take profit|target)\s*(?:\d+)?\s*(?:open|at|target)?[:\s]*(' + price_pattern + r')'
        tp_matches = re.finditer(tp_label_pattern, message_lower)
        for tp_match in tp_matches:
            try:
                val = float(tp_match.group(1))
                if val not in prices["take_profits"]:
                    prices["take_profits"].append(val)
            except (ValueError, IndexError):
                continue
        
        # Also look for format like "(4594 / 4592 / 4588 / 4583)" which often follows a TP label
        list_patterns = [
            r'(?:tp|take profit|target)s?[:\s]*(' + price_pattern + r'(?:\s*[/|]\s*' + price_pattern + r')*)',
            r'\(\s*(' + price_pattern + r'(?:\s*[/|]\s*' + price_pattern + r')*)\s*\)' # Parenthesis list
        ]
        for pattern in list_patterns:
            list_match = re.search(pattern, message_lower)
            if list_match:
                parts = re.findall(price_pattern, list_match.group(1))
                for p in parts:
                    val = float(p)
                    if val not in prices["take_profits"]:
                        prices["take_profits"].append(val)

        if prices["take_profits"]:
            prices["take_profit"] = prices["take_profits"][0]
            
        # Fallback for single TP
        if not prices["take_profit"]:
             tp_patterns = [
                r'(?:tp|take profit|target)[:\s]*(' + price_pattern + r')',
            ]
             for pattern in tp_patterns:
                match = re.search(pattern, message_lower)
                if match:
                    prices["take_profit"] = float(match.group(1))
                    if prices["take_profit"] not in prices["take_profits"]:
                        prices["take_profits"].append(prices["take_profit"])
                    break
        
        # General Fallback - but be careful not to pick up small digits that are likely labels
        all_numbers = [float(n) for n in re.findall(price_pattern, message_text)]
        # Significant numbers are those > 10 or close to entry
        significant_numbers = []
        for n in all_numbers:
            if n > 10:
                significant_numbers.append(n)
            elif prices["entry"]:
                ratio = n / prices["entry"]
                if 0.5 < ratio < 2.0:
                    significant_numbers.append(n)

        found_values = [v for v in [prices["entry"], prices["stop_loss"]] if v is not None]
        if prices["entry_range"]:
            found_values.extend(prices["entry_range"])
        found_values.extend(prices["take_profits"])
        
        # Greedy TP extraction: any significant number not yet assigned might be a TP
        # (especially if it follows the entry price in the message)
        remaining_numbers = [n for n in significant_numbers if n not in found_values]
        
        if not prices["entry"] and significant_numbers:
            prices["entry"] = significant_numbers[0]
            if prices["entry"] in remaining_numbers:
                remaining_numbers.remove(prices["entry"])
            
        if not prices["stop_loss"] and remaining_numbers:
            # SL is usually the "other" side of entry than TPs
            # But the heuristic here is simple: first remaining
            prices["stop_loss"] = remaining_numbers[0]
            remaining_numbers = remaining_numbers[1:]
            
        # Add all truly remaining significant numbers to take_profits
        for n in remaining_numbers:
            if n not in prices["take_profits"]:
                prices["take_profits"].append(n)

        if not prices["take_profit"] and prices["take_profits"]:
            prices["take_profit"] = prices["take_profits"][0]
            
        return prices
    
    def _calculate_confidence(
        self,
        signal_type: Optional[str],
        symbol: Optional[str],
        entry: Optional[float],
        stop_loss: Optional[float],
        take_profit: Optional[float],
        message_text: str
    ) -> float:
        """Calculate confidence score for parsed signal."""
        confidence = 0.5  # Base confidence
        
        # Increase for each extracted field
        if signal_type:
            confidence += 0.15
        if symbol:
            confidence += 0.15
        if entry:
            confidence += 0.10
        if stop_loss:
            confidence += 0.10
        if take_profit:
            confidence += 0.10
        
        # Message quality factors
        if len(message_text) > 50:
            confidence += 0.05
        if len(message_text) < 10:
            confidence -= 0.2
        
        # Penalize if critical fields missing
        if not symbol or not signal_type:
            confidence *= 0.7
        
        return min(1.0, max(0.0, confidence))
    
    def _error_response(self, error_message: str) -> Dict[str, Any]:
        """Return error response."""
        return {
            "signal_type": None,
            "symbol": None,
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
            "confidence_score": 0.0,
            "parsing_method": "error",
            "error": error_message,
            "valid": False,
            "parsed_at": datetime.utcnow().isoformat(),
        }
    
    def validate_signal(self, parsed_signal: Dict[str, Any]) -> bool:
        """Validate parsed signal for execution."""
        # Check required fields
        if not parsed_signal.get("symbol") or not parsed_signal.get("signal_type"):
            return False
        
        # Check confidence threshold
        if parsed_signal.get("confidence_score", 0) < 0.5:
            return False
        
        # Validate price consistency
        entry = parsed_signal.get("entry_price")
        sl = parsed_signal.get("stop_loss")
        tp = parsed_signal.get("take_profit")
        
        if entry and sl and tp:
            # For buy: entry < tp and entry > sl
            # For sell: entry > tp and entry < sl
            signal_type = parsed_signal.get("signal_type")
            
            if signal_type == SignalType.BUY.value:
                if not (sl < entry < tp):
                    return False
            elif signal_type == SignalType.SELL.value:
                if not (tp < entry < sl):
                    return False
        
        return True
