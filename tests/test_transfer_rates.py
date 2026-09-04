from sharewarez.transfer_rates import TransferRates


def test_eight_second_window_and_attempt_isolation():
    rates = TransferRates()
    assert rates.observe(1, 0, 0, 0) is None
    for second in range(1, 10):
        assert rates.observe(1, second * 100, second, second) == 100
    assert rates.observe(1, 900, 10, 10) == 87.5
    assert rates.observe(2, 1000, 10, 10) is None


def test_stall_zero_and_long_gap_resets():
    rates = TransferRates()
    rates.observe(1, 100, 1, 1)
    assert rates.observe(1, 100, 9, 1) == 0
    assert rates.observe(1, 5000, 50, 50) is None
    assert rates.observe(1, 5100, 51, 51) == 100


def test_duplicate_viewers_and_history_are_bounded():
    rates = TransferRates(capacity=2)
    for _ in range(1000):
        rates.observe(1, 100, 1, 1)
    assert len(rates._samples[1]) == 1
    for second in range(2, 100):
        rates.observe(1, second * 100, second, second)
    assert len(rates._samples[1]) <= 10
    rates.observe(2, 100, 100, 100)
    rates.observe(3, 100, 100, 100)
    assert set(rates._samples) == {2, 3}


def test_counter_or_clock_reset_does_not_produce_negative_rate():
    rates = TransferRates()
    rates.observe(1, 1000, 10, 10)
    assert rates.observe(1, 10, 11, 11) is None
    assert rates.observe(1, 100, 1, 1) is None
