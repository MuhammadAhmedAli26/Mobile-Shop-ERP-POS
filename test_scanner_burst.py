# Test suite: Scanner burst timing and leakage logic
import time

def simulate_scan_stream(chars, interval_ms):
    timestamps = []
    current_time = 1000000.0 # arbitrary ms start
    for c in chars:
        timestamps.append((c, current_time))
        current_time += interval_ms
    return timestamps

def detect_burst(stream, max_interval_ms=45, min_len=6):
    buffer = []
    results = []
    
    for i in range(len(stream)):
        char, t = stream[i]
        if not buffer:
            buffer.append((char, t))
        else:
            prev_char, prev_t = buffer[-1]
            interval = t - prev_t
            if interval <= max_interval_ms:
                buffer.append((char, t))
            else:
                # Interrupted, check if previous buffer was a scan
                if len(buffer) >= min_len:
                    results.append(buffer)
                buffer = [(char, t)]
                
    if len(buffer) >= min_len:
        results.append(buffer)
    return results

def run_tests():
    print("--- RUNNING SCANNER BURST & TIMING TESTS ---")
    
    # 1. 5ms burst (Typical high-speed USB laser scanner)
    stream_5ms = simulate_scan_stream("351476312498444", 5.0)
    res_5ms = detect_burst(stream_5ms)
    assert len(res_5ms) == 1, "Failed 5ms laser scan detection"
    assert len(res_5ms[0]) == 15, "Incomplete 5ms buffer"
    print("Test 1 Passed: 5ms USB Laser scan burst correctly identified (15 digits)")

    # 2. 15ms burst (Standard 2D CMOS Imager scanner)
    stream_15ms = simulate_scan_stream("8901234567890", 15.0)
    res_15ms = detect_burst(stream_15ms)
    assert len(res_15ms) == 1, "Failed 15ms 2D imager scan detection"
    assert len(res_15ms[0]) == 13, "Incomplete 15ms buffer"
    print("Test 2 Passed: 15ms 2D CMOS Imager scan burst correctly identified")

    # 3. 30ms burst (Older USB barcode wand / Bluetooth scanner)
    stream_30ms = simulate_scan_stream("PKG-USB-9921", 30.0)
    res_30ms = detect_burst(stream_30ms)
    assert len(res_30ms) == 1, "Failed 30ms scanner detection"
    print("Test 3 Passed: 30ms Bluetooth/Wand scanner burst correctly identified")

    # 4. Manual typing (120ms human keypresses) - must NOT trigger scanner
    stream_human = simulate_scan_stream("samsung a15", 120.0)
    res_human = detect_burst(stream_human)
    assert len(res_human) == 0, f"Human typing triggered scanner: {res_human}"
    print("Test 4 Passed: Human manual typing (120ms) correctly ignored by burst detector")

    # 5. Mixed: human typing followed by idle pause and then instant scanner burst
    typing = simulate_scan_stream("hello", 150.0)
    last_type_time = typing[-1][1]
    # 500ms pause while grabbing the barcode scanner
    scan = []
    t_curr = last_type_time + 500.0
    for c in "359988112233445":
        scan.append((c, t_curr))
        t_curr += 10.0
    mixed_stream = typing + scan
    res_mixed = detect_burst(mixed_stream)
    assert len(res_mixed) == 1, "Failed mixed stream burst isolation"
    scanned_code = "".join([c for c, t in res_mixed[0]])
    assert scanned_code == "359988112233445", f"Wrong code extracted: {scanned_code}"
    print("Test 5 Passed: Scanner burst isolated from manual typing in mixed stream")

    print("\nALL SCANNER BURST TESTS PASSED! (5/5)")

if __name__ == "__main__":
    run_tests()
