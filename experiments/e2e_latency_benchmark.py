import time
import statistics
import csv

from pymodbus.client import ModbusTcpClient
from asyncua.sync import Client as OpcClient




SAMPLES = 500

MIDDLEWARE_IP = "192.168.100.10"

SIEMENS_IP = "192.168.50.10"
AB_IP = "192.168.50.20"
OPTA_IP = "192.168.50.30"

MODBUS_PORT = 502

AB_SLAVE = 1
OPTA_SLAVE = 255

OUTPUT_FILE = "e2e_latency_results.csv"


# Siemens node used for direct benchmark
SIEMENS_NODE = "ns=4;i=7"


results = []


# ============================================================
# STATISTICS
# ============================================================

def calculate_statistics(times):

    times_sorted = sorted(times)

    return {"mean_ms":statistics.mean(times),"std_ms":statistics.stdev(times) if len(times) > 1 else 0,
            "min_ms":min(times),"max_ms":max(times),"median_ms":statistics.median(times),
            "p95_ms":times_sorted[max(0, int(0.95 * len(times)) - 1)],
            "p99_ms":times_sorted[max(0, int(0.99 * len(times)) - 1)]
    }


# ============================================================
# DIRECT MODBUS
# ============================================================

def benchmark_direct_modbus(ip,label,slave_id):

    print()
    print("=" * 70)
    print(f"DIRECT: {label}")
    print("=" * 70)

    client = ModbusTcpClient(
        ip,
        port=MODBUS_PORT
    )

    if not client.connect():

        raise RuntimeError(
            f"Could not connect to {ip}"
        )

    times = []

    failures = 0

    try:

        # Warm-up
        client.read_coils(
            address=0,
            count=1,
            slave=slave_id
        )

        for i in range(SAMPLES):

            t0 = time.perf_counter()

            response = client.read_coils(
                address=0,
                count=1,
                slave=slave_id
            )

            elapsed = (
                time.perf_counter() - t0
            ) * 1000

            if response.isError():

                failures += 1
                continue

            times.append(elapsed)

    finally:

        client.close()

    stats = calculate_statistics(times)

    print(
        f"Mean = {stats['mean_ms']:.3f} ms | "
        f"Std = {stats['std_ms']:.3f} ms | "
        f"Min = {stats['min_ms']:.3f} ms | "
        f"Max = {stats['max_ms']:.3f} ms"
    )

    return times


# ============================================================
# DIRECT OPC-UA
# ============================================================

def benchmark_direct_opcua(
    ip,
    label,
    node_id
):

    print()
    print("=" * 70)
    print(f"DIRECT: {label}")
    print("=" * 70)

    times = []

    with OpcClient(
        f"opc.tcp://{ip}:4840"
    ) as client:

        node = client.get_node(node_id)

        # Warm-up
        node.read_value()

        for i in range(SAMPLES):

            t0 = time.perf_counter()

            node.read_value()

            elapsed = (
                time.perf_counter() - t0
            ) * 1000

            times.append(elapsed)

    stats = calculate_statistics(times)

    print(
        f"Mean = {stats['mean_ms']:.3f} ms | "
        f"Std = {stats['std_ms']:.3f} ms | "
        f"Min = {stats['min_ms']:.3f} ms | "
        f"Max = {stats['max_ms']:.3f} ms"
    )

    return times


# ============================================================
# MIDDLEWARE OPC-UA NODE RESOLUTION
# ============================================================

def get_benchmark_nodes(client):

    namespace = client.get_namespace_index(
        "urn:MATRIX.Middleware.OPC-UA"
    )

    objects = client.nodes.objects

    matrix = objects.get_child(
        f"{namespace}:MATRIX"
    )

    benchmark = matrix.get_child(
        f"{namespace}:Benchmark"
    )

    return {

        "siemens": (
            benchmark.get_child(
                f"{namespace}:Siemens_Request"
            ),
            benchmark.get_child(
                f"{namespace}:Siemens_Response"
            )
        ),

        "ab": (
            benchmark.get_child(
                f"{namespace}:AB_Request"
            ),
            benchmark.get_child(
                f"{namespace}:AB_Response"
            )
        ),

        "opta": (
            benchmark.get_child(
                f"{namespace}:Opta_Request"
            ),
            benchmark.get_child(
                f"{namespace}:Opta_Response"
            )
        )
    }


# ============================================================
# MIDDLEWARE E2E BENCHMARK
# ============================================================

def benchmark_middleware(
    client,
    request_node,
    response_node,
    label
):

    print()
    print("=" * 70)
    print(f"MIDDLEWARE E2E: {label}")
    print("=" * 70)

    times = []

    failures = 0

    # Get current response counter
    sequence = int(
        response_node.read_value()
    )

    # --------------------------------------------------------
    # Warm-up
    # --------------------------------------------------------

    sequence += 1

    request_node.write_value(sequence)

    timeout = 5.0

    start_wait = time.perf_counter()

    while True:

        response = int(
            response_node.read_value()
        )

        if response == sequence:
            break

        if (
            time.perf_counter() - start_wait
            > timeout
        ):

            raise TimeoutError(
                f"Warm-up timeout: {label}"
            )

        time.sleep(0.0005)

    # --------------------------------------------------------
    # Actual measurements
    # --------------------------------------------------------

    for i in range(SAMPLES):

        sequence += 1

        t0 = time.perf_counter()

        request_node.write_value(sequence)

        while True:

            response = int(
                response_node.read_value()
            )

            if response == sequence:
                break

            if (
                time.perf_counter() - t0
                > timeout
            ):

                failures += 1

                print(
                    f"Sample {i + 1}: timeout",
                    flush=True
                )

                break

            time.sleep(0.0002)

        else:

            continue

        if response == sequence:

            elapsed = (
                time.perf_counter() - t0
            ) * 1000

            times.append(elapsed)

    if not times:

        raise RuntimeError(
            f"No successful measurements for {label}"
        )

    stats = calculate_statistics(times)

    print(
        f"Mean = {stats['mean_ms']:.3f} ms | "
        f"Std = {stats['std_ms']:.3f} ms | "
        f"Min = {stats['min_ms']:.3f} ms | "
        f"Max = {stats['max_ms']:.3f} ms"
    )

    print(
        f"Successful = {len(times)} | "
        f"Failed = {failures}"
    )

    return times


# ============================================================
# MAIN EXPERIMENT
# ============================================================

def main():

    print()
    print("=" * 70)
    print("MATRIX ICS TESTBED")
    print("END-TO-END LATENCY BENCHMARK")
    print("=" * 70)

    print(
        f"\nSamples per condition: {SAMPLES}"
    )

    # ========================================================
    # DIRECT PATH
    # ========================================================

    direct = {}

    direct["Siemens S7-1200"] = (
        benchmark_direct_opcua(
            SIEMENS_IP,
            "Siemens S7-1200 (OPC UA)",
            SIEMENS_NODE
        )
    )

    direct["Allen-Bradley Micro820"] = (
        benchmark_direct_modbus(
            AB_IP,
            "Allen-Bradley Micro820 (Modbus TCP)",
            AB_SLAVE
        )
    )

    direct["Arduino Opta"] = (
        benchmark_direct_modbus(
            OPTA_IP,
            "Arduino Opta (Modbus TCP)",
            OPTA_SLAVE
        )
    )

    # ========================================================
    # MIDDLEWARE PATH
    # ========================================================

    middleware = {}

    with OpcClient(
        f"opc.tcp://{MIDDLEWARE_IP}:4840"
    ) as client:

        benchmark_nodes = (
            get_benchmark_nodes(client)
        )

        middleware["Siemens S7-1200"] = (
            benchmark_middleware(
                client,
                benchmark_nodes["siemens"][0],
                benchmark_nodes["siemens"][1],
                "Siemens S7-1200"
            )
        )

        middleware["Allen-Bradley Micro820"] = (
            benchmark_middleware(
                client,
                benchmark_nodes["ab"][0],
                benchmark_nodes["ab"][1],
                "Allen-Bradley Micro820"
            )
        )

        middleware["Arduino Opta"] = (
            benchmark_middleware(
                client,
                benchmark_nodes["opta"][0],
                benchmark_nodes["opta"][1],
                "Arduino Opta"
            )
        )

    # ========================================================
    # CALCULATE OVERHEAD
    # ========================================================

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)

    for device in direct:

        direct_stats = calculate_statistics(
            direct[device]
        )

        middleware_stats = calculate_statistics(
            middleware[device]
        )

        overhead_ms = (
            middleware_stats["mean_ms"]
            -
            direct_stats["mean_ms"]
        )

        overhead_percent = (
            overhead_ms
            /
            direct_stats["mean_ms"]
        ) * 100

        print()
        print(device)

        print(
            f"  Direct mean      : "
            f"{direct_stats['mean_ms']:.3f} ms"
        )

        print(
            f"  Middleware mean  : "
            f"{middleware_stats['mean_ms']:.3f} ms"
        )

        print(
            f"  Added latency    : "
            f"{overhead_ms:.3f} ms"
        )

        print(
            f"  Middleware cost  : "
            f"{overhead_percent:.2f}%"
        )

        results.append({

            "device": device,

            "direct_mean_ms":
                direct_stats["mean_ms"],

            "direct_std_ms":
                direct_stats["std_ms"],

            "direct_min_ms":
                direct_stats["min_ms"],

            "direct_max_ms":
                direct_stats["max_ms"],

            "direct_median_ms":
                direct_stats["median_ms"],

            "direct_p95_ms":
                direct_stats["p95_ms"],

            "direct_p99_ms":
                direct_stats["p99_ms"],

            "middleware_mean_ms":
                middleware_stats["mean_ms"],

            "middleware_std_ms":
                middleware_stats["std_ms"],

            "middleware_min_ms":
                middleware_stats["min_ms"],

            "middleware_max_ms":
                middleware_stats["max_ms"],

            "middleware_median_ms":
                middleware_stats["median_ms"],

            "middleware_p95_ms":
                middleware_stats["p95_ms"],

            "middleware_p99_ms":
                middleware_stats["p99_ms"],

            "added_latency_ms":
                overhead_ms,

            "middleware_overhead_percent":
                overhead_percent
        })

    # ========================================================
    # SAVE SUMMARY
    # ========================================================

    with open(
        "e2e_latency_summary.csv",
        "w",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=results[0].keys()
        )

        writer.writeheader()

        writer.writerows(results)

    # ========================================================
    # SAVE RAW SAMPLES
    # ========================================================

    with open(
        "e2e_latency_raw.csv",
        "w",
        newline=""
    ) as f:

        writer = csv.writer(f)

        writer.writerow([
            "device",
            "path",
            "sample",
            "latency_ms"
        ])

        for device in direct:

            for i, value in enumerate(
                direct[device],
                start=1
            ):

                writer.writerow([
                    device,
                    "Direct",
                    i,
                    value
                ])

            for i, value in enumerate(
                middleware[device],
                start=1
            ):

                writer.writerow([
                    device,
                    "Middleware",
                    i,
                    value
                ])

    print()
    print("=" * 70)
    print("EXPERIMENT COMPLETE")
    print("=" * 70)

    print(
        "\nGenerated:"
        "\n  e2e_latency_summary.csv"
        "\n  e2e_latency_raw.csv"
    )


if __name__ == "__main__":
    main()