/** A job's summary and failures as the §10 contract serves them. */
import type { FailureCluster, JobFailures, JobSummary } from "../../../apiJob";

export const JOB = "0.0.2-rc.1";

export function jobSummaryFixture(over: Partial<JobSummary> = {}): JobSummary {
  return {
    verstr: JOB, name: "lr_layers_grid", idx: 36, status: "succeeded", tree_status: "running",
    kind: "outer", sweep: false,
    total: 2000, counts: { running: 40, waiting: 548, succeeded: 1409, failed: 3, stuck: 0 },
    done: 1412, expected: 2000, progress: 0.706, failed_pct: 1.5, throughput_per_min: 41, eta_sec: 840,
    started_at: "2026-10-14T10:00:00Z", finished_at: null,
    metric: "val_loss",
    metrics: {
      val_loss: {
        n: 1409, min: 0.182, max: 0.9, mean: 0.4, best: 0.182, best_verstr: "0.0.2-dev.t1903",
        hist: [{ lo: 0.182, hi: 0.5, count: 900 }, { lo: 0.5, hi: 0.9, count: 509 }],
        p10: 0.2, p50: 0.38, p90: 0.7,
      },
      acc: {
        n: 1409, min: 0.1, max: 0.95, mean: 0.6, best: 0.95, best_verstr: "0.0.2-dev.t7",
        hist: [{ lo: 0.1, hi: 0.95, count: 1409 }], p10: 0.3, p50: 0.6, p90: 0.9,
      },
    },
    duration: { n: 1412, p50: 150, p90: 420 },
    failures: [{ sig: "failed | exit=<n>", label: "exit <n>", count: 3 }],
    top: [
      { verstr: "0.0.2-dev.t1903", idx: 1903, name: "t1903", status: "succeeded", value: 0.182 },
      { verstr: "0.0.2-dev.t12", idx: 12, name: null, status: "succeeded", value: 0.19 },
    ],
    timeline: {
      bucket_sec: 60, start: 1_760_436_000,
      buckets: [
        { t: 1_760_436_000, started: 50, succeeded: 0, failed: 0 },
        { t: 1_760_436_060, started: 10, succeeded: 30, failed: 1 },
      ],
    },
    ...over,
  };
}

export function clusterFixture(over: Partial<FailureCluster> = {}): FailureCluster {
  return {
    sig: "failed | msg=CUDA out of memory. Tried to allocate <n> GiB", label: "CUDA out of memory",
    count: 2, share: 0.6667, first_at: "2026-10-14T10:05:00Z", last_at: "2026-10-14T11:00:00Z",
    hosts: [{ host: "gpu-3", count: 2 }],
    params: [{ key: "batch_size", value: 512, share: 0.94, base_share: 0.25 }],
    example_verstr: "0.0.2-dev.t44",
    ...over,
  };
}

export function failuresFixture(clusters: FailureCluster[] = [
  clusterFixture(),
  clusterFixture({ sig: "stuck", label: "stuck (no heartbeat)", count: 1, share: 0.3333, params: [], example_verstr: "0.0.2-dev.t9" }),
]): JobFailures {
  return { total_failed: clusters.reduce((n, c) => n + c.count, 0), clusters };
}
