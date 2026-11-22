# Exp3 · two 1000genome workflows through the network agent

## Per workflow

| | WF-A | WF-B |
|---|---|---|
| start | 09:00 | 09:10 |
| tasks_done | 52 | 52 |
| tasks | 52 | 52 |
| makespan_min | 56.4 | 63.4 |
| compute_only_makespan_min | 34.1 | 34.1 |
| inputs_staged_min | 21.9 | 28.9 |
| booked_transfers | 6 | 6 |
| booked_TB | 12.89 | 12.89 |
| best_effort_transfers | 29 | 29 |
| best_effort_GB | 3.3 | 3.3 |
| deadlines_met | 6 | 5 |
| deadline_relaxed | 0 | 1 |
| limited_by | {'background_traffic': 2, 'None': 4} | {'background_traffic': 3, 'None': 3} |
| mean_booked_gbps | 66.7 | 70.0 |
| mean_wait_to_start_min | 1.33 | 6.17 |

Runtime (graph B): {'ticks': 15, 'deviations': 0, 'reports': 0}

Demand forecast (part B): {'booked_transfers_predicted_before_request': 8, 'booked_transfers': 12, 'first_prediction_abs_error_s': {'mean': 23.4, 'max': 114.7}, 'last_prediction_abs_error_s': {'mean': 5.2, 'max': 15.6}, 'would_not_fit_reports': 8}

## Booked transfers

| WF | file | → | TB | ready | deadline | reserved | Gbps | path | limited_by | finished | first forecast |
|---|---|---|---|---|---|---|---|---|---|---|---|
| WF-A | ALL.chr21.phase3_shapeit2_mvncall_integr | ornl-n01 | 1.34 | 09:00:00 | 09:08:55 | 09:00:00–09:02:58 | 60 | APS-LCRC L0 L1 L2 L3 | background_traffic | 09:02:58 | — |
| WF-A | ALL.chr22.phase3_shapeit2_mvncall_integr | ornl-n01 | 1.40 | 09:00:00 | 09:09:21 | 09:00:00–09:04:40 | 40 | APS-LCRC L0 L1 L4 L5 L3 | None | 09:04:40 | — |
| WF-A | ALL.chr21.100000.vcf | ornl-n01 | 5.07 | 09:00:00 | 09:33:48 | 09:03:00–09:14:16 | 60 | APS-LCRC L0 L1 L2 L3 | background_traffic | 09:14:16 | — |
| WF-A | ALL.chr22.100000.vcf | ornl-n01 | 5.07 | 09:00:00 | 09:33:48 | 09:05:00–09:21:54 | 40 | APS-LCRC L0 L1 L4 L5 L3 | None | 09:21:54 | — |
| WF-A | sifted.SIFT.chr21.txt | anl-n02 | 0.00 | 09:03:10 | 09:03:10 | 09:03:10–09:03:10 | 100 | L3 L2 L1 | None | 09:03:10 | 09:03:01 |
| WF-A | sifted.SIFT.chr22.txt | anl-n02 | 0.00 | 09:05:00 | 09:05:00 | 09:05:00–09:05:00 | 100 | L3 L2 L1 | None | 09:05:00 | 09:04:44 |
| WF-B | ALL.chr21.phase3_shapeit2_mvncall_integr | ornl-n01 | 1.34 | 09:10:00 | 09:18:55 | 09:15:00–09:17:58 | 60 | APS-LCRC L0 L1 L2 L3 | background_traffic | 09:17:58 | 09:10:00 |
| WF-B | ALL.chr22.phase3_shapeit2_mvncall_integr | ornl-n01 | 1.40 | 09:10:00 | 09:19:21 | 09:18:00–09:21:07 | 60 | APS-LCRC L0 L1 L2 L3 | background_traffic | 09:21:07 | 09:10:00 |
| WF-B | ALL.chr21.100000.vcf | ornl-n01 | 5.07 | 09:10:00 | 09:43:48 | 09:22:00–09:33:16 | 60 | APS-LCRC L0 L1 L2 L3 | background_traffic | 09:33:16 | 09:10:00 |
| WF-B | ALL.chr22.100000.vcf | ornl-n01 | 5.07 | 09:10:00 | 09:43:48 | 09:22:00–09:38:54 | 40 | APS-LCRC L0 L1 L4 L5 L3 | None | 09:38:54 | 09:10:00 |
| WF-B | sifted.SIFT.chr21.txt | anl-n02 | 0.00 | 09:18:10 | 09:18:10 | 09:18:10–09:18:10 | 100 | L3 L2 L1 | None | 09:18:10 | 09:18:58 |
| WF-B | sifted.SIFT.chr22.txt | anl-n02 | 0.00 | 09:21:20 | 09:21:20 | 09:21:20–09:21:20 | 100 | L3 L2 L1 | None | 09:21:20 | 09:19:25 |

## Graph B findings (no events injected)

- none
