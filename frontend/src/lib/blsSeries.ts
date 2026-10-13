import type { IndicatorDataset } from "../api/types";
import { fmtCompact } from "./format";

// BLS series a WARN chart can be compared against (WarnTimeChart's Compare
// mode). Units and formats mirror IndicatorChart's DATASETS.

export interface BlsOption {
  dataset: IndicatorDataset;
  /** Measure key inside the dataset's `values`. */
  key: string;
  label: string;
  format: (v: number) => string;
}

export const BLS_UNEMPLOYMENT: BlsOption = {
  dataset: "unemployment",
  key: "u3",
  label: "Unemployment rate",
  format: (v) => `${v}%`,
};
export const BLS_JOLTS_LAYOFFS: BlsOption = {
  dataset: "jolts",
  key: "layoffs",
  label: "Layoffs & discharges (JOLTS)",
  format: (v) => fmtCompact(v * 1000),
};
export const BLS_PAYROLLS: BlsOption = {
  dataset: "payrolls",
  key: "employment",
  label: "Sector jobs",
  format: (v) => fmtCompact(v * 1000),
};
