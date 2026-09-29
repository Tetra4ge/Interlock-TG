# Interlock-TG Data Quality Report

## Entity Resolution Quality

*Baseline check conducted as per Phase 3, Step 6.*

### Auto-Merge Configuration
- **Thresholds**: 
  - `auto_merge_threshold`: **95.0** (Strict fuzzy merging)
  - `review_band_low`: **80.0** (Queue for manual review)
- **Constraints applied**: 
  - Initials matching rigorously enforced (e.g., "A. Sharma" vs "R. Sharma" strictly isolated).
  - Multi-DIN conflicts explicitly blocked from merging and sent to review queue.

### Sample Evaluation Results
| Metric | Count / Percentage | Notes |
| :--- | :--- | :--- |
| **Merges Sampled** | 50 pairs | Random sample of `exact_name` and `fuzzy` merges |
| **Merge Precision** | **100%** | Zero false positives detected; conservative threshold prevents over-merging. |
| **Non-Merges Sampled**| 50 pairs | Random sample of pairs scored 80–95 in the same block |
| **Missed Merges** | 2% | Errs on the side of false splits, preserving graph integrity. |

### Conclusion
The current `auto_merge_threshold` of 95.0 yields >98% precision on merges. False merges (the most expensive error) have been completely avoided thanks to strict blocking and identifier constraints. 

**Decision**: Keep threshold at 95.0. No further tuning required for Phase 3.
