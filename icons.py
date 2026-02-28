#!/usr/bin/env python3
"""
NWS Weather TUI — ASCII art icons and icon selection.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

WS_RE = re.compile(r"\s+")

ICON_BIG: Dict[str, str] = {
    "clear_day": r"""
       \   /    
        .-.     
     ― (   ) ―  
        `-’     
       /   \    
""",
    "clear_night": r"""
       .     .  
    .  *  .   . 
       .   *    
   .   .   .    
      *     .   
""",
    "partly_cloudy_day": r"""
   \  /         
 _ /"".-       
   \_(   ).     
   /(___(__)    
""",
    "partly_cloudy_night": r"""
    .     .      
  .   *   .      
     _.._        
   .(    ).      
   (__.___)      
""",
    "cloudy": r"""
     .--.        
  .-(    ).      
 (___.__)__)     
""",
    "rain": r"""
     .--.        
  .-(    ).      
 (___.__)__)    
  ' ' ' '       
   ' ' '        
""",
    "showers": r"""
     .--.        
  .-(    ).      
 (___.__)__)    
  ' '  ' '      
   ' ' '        
""",
    "thunder": r"""
     .--.        
  .-(    ).      
 (___.__)__)    
    ⚡⚡⚡        
   ' ' ' '       
""",
    "snow": r"""
     .--.        
  .-(    ).      
 (___.__)__)    
   *  *  *       
  *  *  *        
""",
    "fog": r"""
  _ - _ - _ - _   
   _ - _ - _ -    
  _ - _ - _ - _   
""",
    "wind": r"""
  ~\  ~\   ~~\     
    ~~\  ~~\   ~~  
  ~\    ~~\        
""",
    "unknown": r"""
     #####
  ##     ##
        ##
       ##
      
       ##
""",
}

ICON_TINY: Dict[str, str] = {
    "clear_day": "☀",
    "clear_night": "☾",
    "partly_cloudy_day": "⛅",
    "partly_cloudy_night": "☁☾",
    "cloudy": "☁",
    "rain": "☔",
    "showers": "☔",
    "thunder": "⚡",
    "snow": "❄",
    "fog": "≋",
    "wind": "〰",
    "unknown": "?",
}


def normalize_text(s: str) -> str:
    return WS_RE.sub(" ", (s or "").strip()).lower()


def pick_icon(short_forecast: str, is_day: Optional[bool]) -> str:
    t = normalize_text(short_forecast)
    if any(k in t for k in ["thunder", "t-storm", "tstorm", "storm"]):
        return "thunder"
    if any(k in t for k in ["snow", "flurr", "sleet", "wintry", "blizzard", "ice"]):
        return "snow"
    if any(k in t for k in ["rain", "showers", "drizzle", "sprinkles"]):
        if "showers" in t or "scattered" in t:
            return "showers"
        return "rain"
    if any(k in t for k in ["fog", "haze", "mist", "smoke"]):
        return "fog"
    if "wind" in t or "breezy" in t or "gust" in t:
        return "wind"
    if "partly" in t or "mostly sunny" in t or "mostly clear" in t:
        return "partly_cloudy_day" if is_day is not False else "partly_cloudy_night"
    if "cloud" in t or "overcast" in t:
        return "cloudy"
    if any(k in t for k in ["sunny", "clear"]):
        return "clear_day" if is_day is not False else "clear_night"
    return "unknown"
