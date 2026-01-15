"""
Pattern Detectors Module

Modular candlestick pattern detection system.
"""

from .base_pattern import BasePatternDetector
from .reversal_patterns import (
    BullishEngulfingDetector,
    BearishEngulfingDetector,
    HammerDetector,
    ShootingStarDetector,
    InvertedHammerDetector,
    HangingManDetector,
    MorningStarDetector,
    EveningStarDetector,
    PiercingPatternDetector,
    DarkCloudCoverDetector,
)
from .continuation_patterns import (
    BullishMarubozuDetector,
    BearishMarubozuDetector,
    RisingThreeMethodsDetector,
    FallingThreeMethodsDetector,
)
from .indecision_patterns import (
    DojiDetector,
    SpinningTopDetector,
    LongLeggedDojiDetector,
)
from .multi_candle_patterns import (
    ThreeWhiteSoldiersDetector,
    ThreeBlackCrowsDetector,
)

__all__ = [
    'BasePatternDetector',
    'BullishEngulfingDetector',
    'BearishEngulfingDetector',
    'HammerDetector',
    'ShootingStarDetector',
    'InvertedHammerDetector',
    'HangingManDetector',
    'MorningStarDetector',
    'EveningStarDetector',
    'PiercingPatternDetector',
    'DarkCloudCoverDetector',
    'BullishMarubozuDetector',
    'BearishMarubozuDetector',
    'RisingThreeMethodsDetector',
    'FallingThreeMethodsDetector',
    'DojiDetector',
    'SpinningTopDetector',
    'LongLeggedDojiDetector',
    'ThreeWhiteSoldiersDetector',
    'ThreeBlackCrowsDetector',
]
