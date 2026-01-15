"""Shared formatting helper functions for Telegram alerts."""


def format_sector_context(sector_context: dict, is_priority: bool = False) -> str:
    """
    Format sector context section for Telegram alert.

    Args:
        sector_context: Sector context dict with sector performance data
        is_priority: Whether this is a priority alert (for bold formatting)

    Returns:
        Formatted sector context string
    """
    sector_section = "\n\n"

    # Use bold header for priority alerts
    if is_priority:
        sector_section += "<b>📊 SECTOR CONTEXT:</b>\n"
    else:
        sector_section += "📊 <b>Sector Context:</b>\n"

    # Extract sector data
    sector_name = sector_context.get('sector_name', 'Unknown')
    sector_change_10min = sector_context.get('sector_change_10min', 0)
    stock_vs_sector = sector_context.get('stock_vs_sector', 0)
    sector_volume_ratio = sector_context.get('sector_volume_ratio', 1.0)
    sector_momentum = sector_context.get('sector_momentum', 0)
    stocks_up = sector_context.get('stocks_up_10min', 0)
    stocks_down = sector_context.get('stocks_down_10min', 0)
    total_stocks = sector_context.get('total_stocks', 0)

    # Format sector name (replace underscores with spaces, title case)
    display_sector = sector_name.replace('_', ' ').title()

    # Sector performance line
    sector_emoji = "🟢" if sector_change_10min > 0 else "🔴" if sector_change_10min < 0 else "⚪"
    sector_section += f"   <b>Sector:</b> {display_sector} {sector_emoji}\n"
    sector_section += f"   <b>10-min Change:</b> {sector_change_10min:+.2f}%\n"

    # Stock vs Sector differential
    if stock_vs_sector != 0:
        vs_emoji = "⬆️" if stock_vs_sector > 0 else "⬇️"
        vs_desc = "outperforming" if stock_vs_sector > 0 else "underperforming"
        sector_section += f"   <b>vs Sector:</b> {vs_emoji} {vs_desc} by {abs(stock_vs_sector):.2f}%\n"

    # Sector breadth (participation)
    if total_stocks > 0:
        up_pct = (stocks_up / total_stocks) * 100
        down_pct = (stocks_down / total_stocks) * 100
        sector_section += f"   <b>Breadth:</b> {stocks_up}↑ ({up_pct:.0f}%) / {stocks_down}↓ ({down_pct:.0f}%)\n"

    # Volume context
    if sector_volume_ratio != 1.0:
        vol_emoji = "🔥" if sector_volume_ratio > 1.2 else "📊"
        sector_section += f"   {vol_emoji} <b>Volume:</b> {sector_volume_ratio:.2f}x average\n"

    # Momentum summary
    if sector_momentum != 0:
        mom_emoji = "🚀" if sector_momentum > 0 else "🔻"
        sector_section += f"   {mom_emoji} <b>Momentum:</b> {sector_momentum:+.2f}\n"

    return sector_section


def format_rsi_section(rsi_analysis: dict, is_priority: bool = False) -> str:
    """
    Format RSI momentum analysis section for Telegram alert.

    Args:
        rsi_analysis: RSI analysis dict with RSI values and crossovers
        is_priority: Whether this is a priority alert (for bold formatting)

    Returns:
        Formatted RSI section string
    """
    rsi_section = "\n\n"

    # Use bold header for priority alerts
    if is_priority:
        rsi_section += "<b>📊 RSI MOMENTUM ANALYSIS:</b>\n"
    else:
        rsi_section += "📊 <b>RSI Momentum Analysis:</b>\n"

    # RSI Values
    rsi_9 = rsi_analysis.get('rsi_9')
    rsi_14 = rsi_analysis.get('rsi_14')
    rsi_21 = rsi_analysis.get('rsi_21')

    if rsi_9 is not None or rsi_14 is not None or rsi_21 is not None:
        rsi_section += "   <b>RSI Values:</b>\n"

        if rsi_9 is not None:
            # Add emoji indicators for overbought/oversold
            if rsi_9 > 70:
                emoji = "🔥"  # Overbought
            elif rsi_9 < 30:
                emoji = "❄️"  # Oversold
            else:
                emoji = "📊"
            rsi_section += f"      {emoji} RSI(9): {rsi_9:.2f}\n"

        if rsi_14 is not None:
            if rsi_14 > 70:
                emoji = "🔥"
            elif rsi_14 < 30:
                emoji = "❄️"
            else:
                emoji = "📊"
            rsi_section += f"      {emoji} RSI(14): {rsi_14:.2f}\n"

        if rsi_21 is not None:
            if rsi_21 > 70:
                emoji = "🔥"
            elif rsi_21 < 30:
                emoji = "❄️"
            else:
                emoji = "📊"
            rsi_section += f"      {emoji} RSI(21): {rsi_21:.2f}\n"

    # RSI Crossovers
    crossovers = rsi_analysis.get('crossovers', {})
    if crossovers:
        rsi_section += "   <b>Crossovers:</b>\n"

        for pair, crossover_data in crossovers.items():
            if crossover_data.get('status') and crossover_data.get('strength') is not None:
                fast, slow = pair.split('_')
                status = crossover_data['status']
                strength = crossover_data['strength']

                # Arrow indicator
                arrow = "↑" if status == 'above' else "↓"
                sign = "+" if strength >= 0 else ""

                rsi_section += f"      • RSI({fast}){arrow}RSI({slow}): {sign}{strength:.2f}\n"

    # Recent Crossovers
    recent_crosses = []
    for pair, crossover_data in crossovers.items():
        recent = crossover_data.get('recent_cross', {})
        if recent.get('occurred'):
            bars_ago = recent.get('bars_ago', 0)
            direction = recent.get('direction', '').capitalize()
            emoji = "🟢" if direction == 'Bullish' else "🔴"
            fast, slow = pair.split('_')
            recent_crosses.append(f"{emoji} RSI({fast})×RSI({slow}) {direction} {bars_ago}d ago")

    if recent_crosses:
        rsi_section += "   <b>Recent Crosses:</b>\n"
        for cross in recent_crosses:
            rsi_section += f"      • {cross}\n"

    # Overall Summary
    summary = rsi_analysis.get('summary', '')
    if summary:
        # Add emoji based on summary
        if 'Bullish' in summary:
            emoji = "🟢"
        elif 'Bearish' in summary:
            emoji = "🔴"
        else:
            emoji = "⚪"

        rsi_section += f"   <b>Summary:</b> {emoji} {summary}\n"

    return rsi_section


def format_oi_section(oi_analysis: dict, is_priority: bool = False) -> str:
    """
    Format OI (Open Interest) analysis section for Telegram alert.

    Args:
        oi_analysis: OI analysis dict with pattern, signal, and strength
        is_priority: Whether this is a priority alert (for bold formatting)

    Returns:
        Formatted OI section string
    """
    oi_section = "\n\n"

    # Use bold header for priority alerts
    if is_priority:
        oi_section += "<b>🔥 OI ANALYSIS:</b> 🔥\n"
    else:
        oi_section += "🔥 <b>OI Analysis:</b>\n"

    # Extract OI data
    pattern = oi_analysis.get('pattern', '')
    signal = oi_analysis.get('signal', '')
    interpretation = oi_analysis.get('interpretation', '')
    oi_change_pct = oi_analysis.get('oi_change_pct', 0)
    strength = oi_analysis.get('strength', '')
    priority = oi_analysis.get('priority', '')
    at_day_high = oi_analysis.get('at_day_high', False)
    at_day_low = oi_analysis.get('at_day_low', False)

    # Pattern and Signal (with emoji indicators)
    pattern_emoji_map = {
        'LONG_BUILDUP': '🟢',
        'SHORT_BUILDUP': '🔴',
        'SHORT_COVERING': '🟡',
        'LONG_UNWINDING': '🟠'
    }
    pattern_emoji = pattern_emoji_map.get(pattern, '📊')

    # Format pattern name for display
    pattern_display = pattern.replace('_', ' ').title()

    oi_section += f"   {pattern_emoji} <b>Pattern:</b> {pattern_display}\n"

    # OI Change with strength indicator
    strength_emoji_map = {
        'VERY_STRONG': '🔥🔥🔥',
        'STRONG': '🔥🔥',
        'SIGNIFICANT': '🔥',
        'MINIMAL': '📊'
    }
    strength_emoji = strength_emoji_map.get(strength, '📊')

    change_sign = "+" if oi_change_pct >= 0 else ""
    oi_section += f"   {strength_emoji} <b>OI Change:</b> {change_sign}{oi_change_pct:.2f}% ({strength})\n"

    # Signal interpretation
    signal_emoji_map = {
        'BULLISH': '🟢',
        'BEARISH': '🔴',
        'WEAK_BULLISH': '🟡',
        'WEAK_BEARISH': '🟠'
    }
    signal_emoji = signal_emoji_map.get(signal, '⚪')

    oi_section += f"   {signal_emoji} <b>Signal:</b> {signal}\n"
    oi_section += f"   💡 <b>Meaning:</b> {interpretation}\n"

    # Priority indicator
    if priority == 'HIGH':
        oi_section += f"   ⚠️ <b>PRIORITY:</b> HIGH - Fresh positions building!\n"
    elif priority == 'MEDIUM':
        oi_section += f"   📌 Priority: Medium\n"

    # OI extremes (only shown when OI change >= 5%)
    if at_day_high:
        oi_section += f"   🎯 <b>At Day High!</b> - OI at intraday peak ({oi_change_pct:+.1f}% from day start)\n"
    elif at_day_low:
        oi_section += f"   📉 <b>At Day Low!</b> - OI at intraday bottom ({oi_change_pct:+.1f}% from day start)\n"

    return oi_section


def score_emoji(score: float) -> str:
    """Get emoji based on score value."""
    if score >= 70:
        return "✅"
    elif score >= 40:
        return "⚠️"
    else:
        return "❌"
