#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Test the fixed YoY/QoQ growth logic
"""

def calculate_growth_metrics_fixed(quarters_data):
    """Fixed version of growth calculation"""
    # YoY Growth
    yoy_revenue_growth = []
    yoy_pat_growth = []

    if len(quarters_data) >= 8:
        for i in range(min(8, len(quarters_data) - 4)):
            current_q = quarters_data[i]
            year_ago_q = quarters_data[i + 4]

            if year_ago_q['revenue'] != 0:
                rev_growth = ((current_q['revenue'] - year_ago_q['revenue']) / abs(year_ago_q['revenue'])) * 100
                yoy_revenue_growth.append(rev_growth)

            if year_ago_q['pat'] != 0:
                pat_growth = ((current_q['pat'] - year_ago_q['pat']) / abs(year_ago_q['pat'])) * 100
                yoy_pat_growth.append(pat_growth)

    # QoQ Growth
    qoq_revenue_growth = []
    qoq_pat_growth = []

    if len(quarters_data) >= 3:
        for i in range(min(3, len(quarters_data) - 1)):
            current_q = quarters_data[i]
            prev_q = quarters_data[i + 1]

            if prev_q['revenue'] != 0:
                rev_growth = ((current_q['revenue'] - prev_q['revenue']) / abs(prev_q['revenue'])) * 100
                qoq_revenue_growth.append(rev_growth)

            if prev_q['pat'] != 0:
                pat_growth = ((current_q['pat'] - prev_q['pat']) / abs(prev_q['pat'])) * 100
                qoq_pat_growth.append(pat_growth)

    # For YoY: Check if majority show growth (at least 2 out of 3)
    yoy_revenue_growing = False
    yoy_pat_growing = False

    if len(yoy_revenue_growth) >= 3:
        recent_rev = yoy_revenue_growth[:3]
        recent_pat = yoy_pat_growth[:3] if len(yoy_pat_growth) >= 3 else []

        yoy_revenue_growing = sum(1 for g in recent_rev if g > 0) >= 2
        yoy_pat_growing = sum(1 for g in recent_pat if g > 0) >= 2 if recent_pat else False

    # For QoQ: Check if average is positive
    qoq_revenue_growing = False
    qoq_pat_growing = False

    if len(qoq_revenue_growth) >= 2:
        avg_qoq_rev = sum(qoq_revenue_growth) / len(qoq_revenue_growth)
        avg_qoq_pat = sum(qoq_pat_growth) / len(qoq_pat_growth) if qoq_pat_growth else 0

        qoq_revenue_growing = avg_qoq_rev > 0
        qoq_pat_growing = avg_qoq_pat > 0

    return {
        'yoy_revenue_avg': sum(yoy_revenue_growth) / len(yoy_revenue_growth) if yoy_revenue_growth else 0,
        'yoy_pat_avg': sum(yoy_pat_growth) / len(yoy_pat_growth) if yoy_pat_growth else 0,
        'qoq_revenue_avg': sum(qoq_revenue_growth) / len(qoq_revenue_growth) if qoq_revenue_growth else 0,
        'qoq_pat_avg': sum(qoq_pat_growth) / len(qoq_pat_growth) if qoq_pat_growth else 0,
        'yoy_revenue_growing': yoy_revenue_growing,
        'yoy_pat_growing': yoy_pat_growing,
        'qoq_revenue_growing': qoq_revenue_growing,
        'qoq_pat_growing': qoq_pat_growing,
        'yoy_rev_detail': yoy_revenue_growth[:3] if len(yoy_revenue_growth) >= 3 else yoy_revenue_growth,
        'yoy_pat_detail': yoy_pat_growth[:3] if len(yoy_pat_growth) >= 3 else yoy_pat_growth,
        'qoq_rev_detail': qoq_revenue_growth,
        'qoq_pat_detail': qoq_pat_growth
    }


def test_case_1():
    """Test case: Strong YoY growth (2 out of 3 positive)"""
    print("\n" + "="*80)
    print("TEST 1: Strong YoY Growth (2 out of 3 positive)")
    print("="*80)

    # Simulated data: Q3'24, Q2'24, Q1'24, Q4'23, Q3'23, Q2'23, Q1'23, Q4'22
    quarters = [
        {'quarter': 'Sep 2024', 'revenue': 120, 'pat': 15},   # Q3'24
        {'quarter': 'Jun 2024', 'revenue': 115, 'pat': 14},   # Q2'24
        {'quarter': 'Mar 2024', 'revenue': 110, 'pat': 13},   # Q1'24
        {'quarter': 'Dec 2023', 'revenue': 105, 'pat': 12},   # Q4'23
        {'quarter': 'Sep 2023', 'revenue': 100, 'pat': 10},   # Q3'23 (YoY: +20%)
        {'quarter': 'Jun 2023', 'revenue': 98, 'pat': 11},    # Q2'23 (YoY: +17.3%, PAT: +27%)
        {'quarter': 'Mar 2023', 'revenue': 95, 'pat': 12},    # Q1'23 (YoY: +15.8%, PAT: +8.3%)
        {'quarter': 'Dec 2022', 'revenue': 90, 'pat': 11},    # Q4'22
    ]

    metrics = calculate_growth_metrics_fixed(quarters)

    print(f"YoY Revenue Growth (last 3): {metrics['yoy_rev_detail']}")
    print(f"YoY PAT Growth (last 3): {metrics['yoy_pat_detail']}")
    print(f"YoY Revenue Avg: {metrics['yoy_revenue_avg']:.2f}%")
    print(f"YoY PAT Avg: {metrics['yoy_pat_avg']:.2f}%")
    print(f"YoY Revenue Growing: {metrics['yoy_revenue_growing']}")
    print(f"YoY PAT Growing: {metrics['yoy_pat_growing']}")

    print(f"\nQoQ Revenue Growth: {metrics['qoq_rev_detail']}")
    print(f"QoQ PAT Growth: {metrics['qoq_pat_detail']}")
    print(f"QoQ Revenue Avg: {metrics['qoq_revenue_avg']:.2f}%")
    print(f"QoQ PAT Avg: {metrics['qoq_pat_avg']:.2f}%")
    print(f"QoQ Revenue Growing: {metrics['qoq_revenue_growing']}")
    print(f"QoQ PAT Growing: {metrics['qoq_pat_growing']}")

    # Should pass YoY
    passes_yoy = metrics['yoy_revenue_growing'] and metrics['yoy_pat_growing']
    passes_qoq = metrics['qoq_revenue_growing'] and metrics['qoq_pat_growing']

    print(f"\n✓ Passes YoY criteria: {passes_yoy}")
    print(f"✓ Passes QoQ criteria: {passes_qoq}")

    return passes_yoy or passes_qoq


def test_case_2():
    """Test case: Mixed YoY (1 negative, 2 positive) - should still pass"""
    print("\n" + "="*80)
    print("TEST 2: Mixed YoY (1 negative, 2 positive) - Should PASS")
    print("="*80)

    quarters = [
        {'quarter': 'Sep 2024', 'revenue': 110, 'pat': 14},   # Q3'24
        {'quarter': 'Jun 2024', 'revenue': 105, 'pat': 13},   # Q2'24
        {'quarter': 'Mar 2024', 'revenue': 100, 'pat': 12},   # Q1'24
        {'quarter': 'Dec 2023', 'revenue': 105, 'pat': 12},   # Q4'23
        {'quarter': 'Sep 2023', 'revenue': 100, 'pat': 10},   # Q3'23 (YoY: +10%)
        {'quarter': 'Jun 2023', 'revenue': 110, 'pat': 11},   # Q2'23 (YoY: -4.5% - NEGATIVE!)
        {'quarter': 'Mar 2023', 'revenue': 90, 'pat': 10},    # Q1'23 (YoY: +11.1%)
        {'quarter': 'Dec 2022', 'revenue': 95, 'pat': 11},    # Q4'22
    ]

    metrics = calculate_growth_metrics_fixed(quarters)

    print(f"YoY Revenue Growth (last 3): {[f'{x:.1f}%' for x in metrics['yoy_rev_detail']]}")
    print(f"YoY PAT Growth (last 3): {[f'{x:.1f}%' for x in metrics['yoy_pat_detail']]}")
    print(f"Positive count (Revenue): {sum(1 for g in metrics['yoy_rev_detail'] if g > 0)}/3")
    print(f"Positive count (PAT): {sum(1 for g in metrics['yoy_pat_detail'] if g > 0)}/3")
    print(f"YoY Revenue Growing: {metrics['yoy_revenue_growing']} (needs 2/3)")
    print(f"YoY PAT Growing: {metrics['yoy_pat_growing']} (needs 2/3)")

    passes = metrics['yoy_revenue_growing'] and metrics['yoy_pat_growing']
    print(f"\n✓ Should PASS (2 out of 3 positive): {passes}")

    return passes


def test_case_3():
    """Test case: Declining - should FAIL"""
    print("\n" + "="*80)
    print("TEST 3: Declining Growth - Should FAIL")
    print("="*80)

    quarters = [
        {'quarter': 'Sep 2024', 'revenue': 90, 'pat': 8},    # Q3'24
        {'quarter': 'Jun 2024', 'revenue': 92, 'pat': 9},    # Q2'24
        {'quarter': 'Mar 2024', 'revenue': 95, 'pat': 10},   # Q1'24
        {'quarter': 'Dec 2023', 'revenue': 100, 'pat': 11},  # Q4'23
        {'quarter': 'Sep 2023', 'revenue': 100, 'pat': 12},  # Q3'23 (YoY: -10%)
        {'quarter': 'Jun 2023', 'revenue': 105, 'pat': 13},  # Q2'23 (YoY: -12.4%)
        {'quarter': 'Mar 2023', 'revenue': 110, 'pat': 14},  # Q1'23 (YoY: -13.6%)
        {'quarter': 'Dec 2022', 'revenue': 115, 'pat': 15},  # Q4'22
    ]

    metrics = calculate_growth_metrics_fixed(quarters)

    print(f"YoY Revenue Growth (last 3): {[f'{x:.1f}%' for x in metrics['yoy_rev_detail']]}")
    print(f"YoY PAT Growth (last 3): {[f'{x:.1f}%' for x in metrics['yoy_pat_detail']]}")
    print(f"YoY Revenue Growing: {metrics['yoy_revenue_growing']}")
    print(f"YoY PAT Growing: {metrics['yoy_pat_growing']}")

    passes = metrics['yoy_revenue_growing'] and metrics['yoy_pat_growing']
    print(f"\n✓ Should FAIL (all negative): {not passes}")

    return not passes  # Should be False


def main():
    print("="*80)
    print("TESTING FIXED YoY/QoQ GROWTH LOGIC")
    print("="*80)

    test1 = test_case_1()
    test2 = test_case_2()
    test3 = test_case_3()

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Test 1 (Strong growth): {'✅ PASS' if test1 else '❌ FAIL'}")
    print(f"Test 2 (Mixed 2/3): {'✅ PASS' if test2 else '❌ FAIL'}")
    print(f"Test 3 (Declining): {'✅ PASS' if test3 else '❌ FAIL'}")
    print("="*80)

    all_pass = test1 and test2 and test3
    if all_pass:
        print("\n✅ ALL TESTS PASSED - Logic is working correctly!")
    else:
        print("\n❌ SOME TESTS FAILED - Logic needs adjustment")


if __name__ == "__main__":
    main()
