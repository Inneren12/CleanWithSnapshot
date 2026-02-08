import { FEATURE_KEYS, type FeatureConfigResponse, type UiPrefsResponse } from "./featureVisibility";

export const DEFAULT_FEATURE_CONFIG: FeatureConfigResponse = {
  org_id: "default",
  overrides: {},
  defaults: {},
  effective: {},
  keys: FEATURE_KEYS,
};

export const DEFAULT_UI_PREFS: UiPrefsResponse = {
  hidden_keys: [],
};
