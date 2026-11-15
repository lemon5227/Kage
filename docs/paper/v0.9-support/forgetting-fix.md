| Variant | Seed (run) | Data change | Learned file | Held-out file | Learned web | Read-back (wrote a file, cp0) | General |
|---|---|---|---|---|---|---|---|
| Base student | `A0@26` | — | 30/72 | 15/36 | 10/54 | — | — |
| R3 | `R3@26` | guided re-execution, guidance removed | 64/72 | 1/36 | 21/54 | — | — |
| R3 | `r3t1@41` | guided re-execution, guidance removed | 63/72 | 0/36 | 26/54 | 0/110 | 28/30 |
| R3 | `r3t2@41` | guided re-execution, guidance removed | 58/72 | 2/36 | 28/54 | 2/113 | 28/30 |
| R3g | `r3g0@44` | R3 + read-back step after each write | 61/72 | 5/36 | 21/54 | 111/111 | 28/30 |
| R3g | `r3g1@44` | R3 + read-back step after each write | 69/72 | 5/36 | 25/54 | 108/108 | 28/30 |
| R3f | `r3f0@F` | R3 + 363 rows of the student's own passing code on other programming families | 57/72 | 15/36 | 30/54 | 0/111 | 28/30 |
| R3f | `r3f1@F` | R3 + 363 rows of the student's own passing code on other programming families | 65/72 | 18/36 | 27/54 | 0/107 | 28/30 |
| R3fg | `r3fg0@F` | R3f + read-back step | 65/72 | 19/36 | 25/54 | 101/102 | 28/30 |
| R3fg | `r3fg1@F` | R3f + read-back step | 63/72 | 13/36 | 26/54 | 102/106 | 28/30 |

Negative-task executions (pooled over the seeds listed, 3 runs each): R3 seeds 1-2 1/72 (stream-v1-lookalike_readonly-10502); R3g 0/72 (none); R3f 3/72 (stream-v1-lookalike_readonly-10502); R3fg 3/72 (stream-v1-lookalike_readonly-10502).

Held-out tasks, rewrite after a read-back: R3g 2 rewrites in 72 read-backs; R3f 0 rewrites in 0 read-backs; R3fg 0 rewrites in 59 read-backs.

Task-level exact sign-flip contrasts (mean difference, improved/worse/tied, nominal p):
- `r3fg_vs_r3f_in`: +0.04, 5/4/15, p = 109/256
- `r3fg_vs_r3f_held`: -0.01, 4/5/3, p = 1/1
- `r3fg_vs_r3t_held`: +0.42, 10/1/1, p = 1/256
- `r3fg_vs_r3g_held`: +0.31, 8/2/2, p = 17/512
- `r3fg0_vs_base26_held`: +0.11, 5/1/6, p = 17/32
- `r3fg1_vs_base26_held`: -0.06, 3/5/4, p = 111/128
- `r3fg0_vs_base26_in`: +0.49, 15/0/9, p = 1/16384
- `r3fg1_vs_base26_in`: +0.46, 15/2/7, p = 5/16384
- `r3f_vs_r3t_held`: +0.43, 10/0/2, p = 1/512
- `r3f_vs_r3g_held`: +0.32, 8/2/2, p = 1/64
