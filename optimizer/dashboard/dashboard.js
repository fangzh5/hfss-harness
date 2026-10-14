(function () {
  const sampleState = {
    title: "case3_mvp Optimization Dashboard",
    meta: {
      source_name: "dipole-patch",
      task_name: "case3_mvp",
    },
    subtitle: "静态布局预览 | 后续只替换数据源即可",
    mode: "Static preview",
    optimization_mode: "single_objective",
    status: {
      label: "Running",
      tone: "running",
      detail: "HFSS solve in progress",
    },
    current: {
      sim_id: 18,
      iter_id: 6,
      stage: "stage_1",
      checkpoint: false,
      elapsed: "01:24:16",
    },
    metrics: {
      best_s11: { value: -18.62, unit: "dB", note: "历史最优" },
      last_s11: { value: -14.28, unit: "dB", note: "上一次仿真" },
      best_s12: { value: -21.04, unit: "dB", note: "历史最优" },
      last_s12: { value: -17.96, unit: "dB", note: "上一次仿真" },
      fitness: { value: -18.62, unit: "cost", note: "当前最优适应度" },
    },
    s11Curves: {
      threshold: -12,
      best: [
        { freq: 50, s11: -8.8 },
        { freq: 52, s11: -11.2 },
        { freq: 54, s11: -14.4 },
        { freq: 56, s11: -16.1 },
        { freq: 58, s11: -18.3 },
        { freq: 60, s11: -20.1 },
        { freq: 62, s11: -18.8 },
        { freq: 64, s11: -16.0 },
        { freq: 67, s11: -13.5 },
      ],
      last: [
        { freq: 50, s11: -7.1 },
        { freq: 52, s11: -9.4 },
        { freq: 54, s11: -11.1 },
        { freq: 56, s11: -12.8 },
        { freq: 58, s11: -14.2 },
        { freq: 60, s11: -15.4 },
        { freq: 62, s11: -14.6 },
        { freq: 64, s11: -13.3 },
        { freq: 67, s11: -11.7 },
      ],
    },
    s12Curves: {
      threshold: -20,
      best: [
        { freq: 50, s12: -11.5 },
        { freq: 52, s12: -13.0 },
        { freq: 54, s12: -14.8 },
        { freq: 56, s12: -16.4 },
        { freq: 58, s12: -17.5 },
        { freq: 60, s12: -18.3 },
        { freq: 62, s12: -19.1 },
        { freq: 64, s12: -20.2 },
        { freq: 67, s12: -21.0 },
      ],
      last: [
        { freq: 50, s12: -10.8 },
        { freq: 52, s12: -12.1 },
        { freq: 54, s12: -13.7 },
        { freq: 56, s12: -15.0 },
        { freq: 58, s12: -16.2 },
        { freq: 60, s12: -17.0 },
        { freq: 62, s12: -17.6 },
        { freq: 64, s12: -18.0 },
        { freq: 67, s12: -18.5 },
      ],
    },
    target: {
      freq_band: [50, 67],
      s11_threshold: -12,
      s12_threshold: -20,
      bandwidth_target: 17.0,
      gain_min: null,
      stages: [
        {
          name: "stage_1",
          freq_band: [50, 67],
          s11_threshold: -12,
          s12_threshold: -15,
          bandwidth_target: 17.0,
          gain_min: null,
        },
      ],
    },
    parameters: [
      {
        name: "dipole_w",
        value: 0.18,
        min: 0.14,
        max: 0.2,
        unit: "mm",
        mode: "count",
        count: 7,
        resolution: 0.01,
        state: "active",
      },
      {
        name: "dipole_g",
        value: 0.41,
        min: 0.3,
        max: 0.55,
        unit: "mm",
        mode: "count",
        count: 7,
        resolution: 0.01,
        state: "active",
      },
      {
        name: "dipole_l",
        value: 1.04,
        min: 0.95,
        max: 1.1,
        unit: "mm",
        mode: "count",
        count: 7,
        resolution: 0.01,
        state: "active",
      },
      {
        name: "dipole_s",
        value: 0.08,
        min: 0.05,
        max: 0.1,
        unit: "mm",
        mode: "count",
        count: 7,
        resolution: 0.01,
        state: "active",
      },
      {
        name: "patch_x",
        value: 0.92,
        min: 0.8,
        max: 0.98,
        unit: "mm",
        mode: "count",
        count: 7,
        resolution: 0.01,
        state: "active",
      },
      {
        name: "patch_y",
        value: 0.95,
        min: 0.88,
        max: 1.02,
        unit: "mm",
        mode: "count",
        count: 7,
        resolution: 0.01,
        state: "active",
      },
      {
        name: "patch_g",
        value: 0.12,
        min: 0.08,
        max: 0.14,
        unit: "mm",
        mode: "count",
        count: 7,
        resolution: 0.01,
        state: "active",
      },
    ],
    fitnessHistory: [
      { sim_id: 1, iter_id: 1, fitness: -10.8 },
      { sim_id: 2, iter_id: 1, fitness: -11.4 },
      { sim_id: 3, iter_id: 2, fitness: -12.2 },
      { sim_id: 4, iter_id: 2, fitness: -13.1 },
      { sim_id: 5, iter_id: 2, fitness: -13.8 },
      { sim_id: 6, iter_id: 3, fitness: -14.7 },
      { sim_id: 7, iter_id: 3, fitness: -15.2 },
      { sim_id: 8, iter_id: 4, fitness: -15.6 },
      { sim_id: 9, iter_id: 4, fitness: -16.1 },
      { sim_id: 10, iter_id: 4, fitness: -16.4 },
      { sim_id: 11, iter_id: 5, fitness: -16.9 },
      { sim_id: 12, iter_id: 5, fitness: -17.2 },
      { sim_id: 13, iter_id: 5, fitness: -17.6 },
      { sim_id: 14, iter_id: 6, fitness: -17.8 },
      { sim_id: 15, iter_id: 6, fitness: -18.0 },
      { sim_id: 16, iter_id: 6, fitness: -18.12 },
      { sim_id: 17, iter_id: 6, fitness: -18.25 },
      { sim_id: 18, iter_id: 6, fitness: -18.62 },
    ],
    events: [
      { time: "12:06:41", message: "sim_id 18 完成，更新 best S11", severity: "success" },
      { time: "12:05:18", message: "iter_id 6 进入后半段评估", severity: "info" },
      { time: "12:02:33", message: "参数边界自动适配完成", severity: "info" },
      { time: "12:01:09", message: "checkpoint 写入成功", severity: "success" },
    ],
  };

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function getNiceTickStep(range, desiredTicks = 6) {
    if (!Number.isFinite(range) || range <= 0) {
      return 1;
    }

    const safeDesiredTicks = Math.max(1, desiredTicks);
    const rawStep = range / safeDesiredTicks;
    if (rawStep <= 1) {
      return 1;
    }

    const exponent = Math.floor(Math.log10(rawStep));
    const base = 10 ** exponent;
    const candidates = [1, 2, 5, 10].map((factor) => factor * base);

    return candidates.reduce((best, candidate) => {
      const bestDelta = Math.abs(best - rawStep);
      const candidateDelta = Math.abs(candidate - rawStep);
      if (candidateDelta < bestDelta) {
        return candidate;
      }
      if (candidateDelta === bestDelta && candidate < best) {
        return candidate;
      }
      return best;
    }, candidates[0]);
  }

  function formatAxisTick(value) {
    const rounded = Math.round(value);
    if (Math.abs(value - rounded) < 1e-6) {
      return String(rounded);
    }
    return formatNumber(value, 0);
  }

  function buildAdaptiveXAxisTicks(min, max, plotWidth) {
    if (!Number.isFinite(min) || !Number.isFinite(max)) {
      return [];
    }
    if (max <= min) {
      return [min];
    }

    const desiredTicks = clamp(Math.round(plotWidth / 170), 4, 8);
    const step = getNiceTickStep(max - min, desiredTicks);
    const epsilon = step * 1e-6;
    const ticks = [];
    const pushTick = (value) => {
      const normalized = Number(value.toFixed(10));
      if (!ticks.some((tick) => Math.abs(tick - normalized) < epsilon)) {
        ticks.push(normalized);
      }
    };

    pushTick(min);

    const firstAligned = Math.ceil(min / step) * step;
    for (let value = firstAligned; value <= max + epsilon; value += step) {
      pushTick(value);
    }

    pushTick(max);
    return ticks.sort((a, b) => a - b);
  }

  function formatNumber(value, digits = 2) {
    if (value === null || value === undefined || value === "") {
      return "N/A";
    }
    const numeric = Number(value);
    if (Number.isNaN(numeric)) {
      return String(value);
    }
    return Number.isInteger(numeric) ? String(numeric) : numeric.toFixed(digits);
  }

  function formatBand(value) {
    if (!Array.isArray(value) || value.length < 2) {
      return "N/A";
    }
    return `${formatNumber(value[0])} - ${formatNumber(value[1])} GHz`;
  }

  function formatValue(value, key) {
    if (value === null || value === undefined || value === "") {
      return "N/A";
    }
    if (Array.isArray(value)) {
      return value.join(" - ");
    }
    if (typeof value === "boolean") {
      return value ? "True" : "False";
    }
    if (typeof value === "number") {
      if (key === "freq_band") {
        return formatNumber(value);
      }
      return formatNumber(value, 3);
    }
    return String(value);
  }

  function formatMetric(metric) {
    if (!metric) {
      return { value: "N/A", note: "" };
    }
    const value = metric.unit && metric.unit !== "cost"
      ? `${formatNumber(metric.value, 2)} ${metric.unit}`
      : formatNumber(metric.value, 2);
    return { value, note: metric.note || "" };
  }

  function themeColor(name, fallback) {
    if (typeof window === "undefined" || typeof getComputedStyle !== "function" || !document?.documentElement) {
      return fallback;
    }
    const value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return value ? value.trim() || fallback : fallback;
  }

  const THEME_PREFERENCE_STORAGE_KEY = "optimizer-dashboard-theme-preference";

  function getSystemThemePreference() {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return "light";
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function getThemePreferenceFromLocation() {
    try {
      const params = new URLSearchParams(window.location.search);
      const theme = params.get("theme");
      return normalizeThemePreference(theme);
    } catch (error) {
      return "auto";
    }
  }

  function normalizeThemePreference(preference) {
    if (preference === "light" || preference === "dark" || preference === "auto") {
      return preference;
    }
    return "auto";
  }

  function readThemePreference() {
    const locationPreference = getThemePreferenceFromLocation();
    if (locationPreference === "light" || locationPreference === "dark") {
      return locationPreference;
    }

    const datasetPreference = document?.documentElement?.dataset?.themePreference;
    const normalizedDatasetPreference = normalizeThemePreference(datasetPreference);
    if (normalizedDatasetPreference !== "auto" || datasetPreference === "auto") {
      return normalizedDatasetPreference;
    }

    try {
      const storedPreference = window.localStorage.getItem(THEME_PREFERENCE_STORAGE_KEY);
      const normalizedStoredPreference = normalizeThemePreference(storedPreference);
      if (normalizedStoredPreference !== "auto" || storedPreference === "auto") {
        return normalizedStoredPreference;
      }
    } catch (error) {
      return normalizedDatasetPreference;
    }

    return normalizedDatasetPreference;
  }

  function resolveThemePreference(preference) {
    const normalizedPreference = normalizeThemePreference(preference);
    if (normalizedPreference === "light" || normalizedPreference === "dark") {
      return normalizedPreference;
    }
    return getSystemThemePreference();
  }

  function nextThemePreference(preference) {
    const normalizedPreference = normalizeThemePreference(preference);
    const resolvedTheme = resolveThemePreference(normalizedPreference);
    if (normalizedPreference === "auto") {
      return resolvedTheme === "dark" ? "light" : "dark";
    }
    if (normalizedPreference === "dark") {
      return "light";
    }
    return "auto";
  }

  function writeThemePreference(preference) {
    try {
      window.localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, preference);
    } catch (error) {
      return;
    }
  }

  function applyThemePreference(preference, { persist = false } = {}) {
    const normalizedPreference = normalizeThemePreference(preference);
    const resolvedTheme = resolveThemePreference(normalizedPreference);
    if (persist) {
      writeThemePreference(normalizedPreference);
    }
    if (document?.documentElement) {
      document.documentElement.dataset.themePreference = normalizedPreference;
      document.documentElement.dataset.theme = resolvedTheme;
    }
    const button = document.getElementById("theme-toggle");
    const state = document.getElementById("theme-toggle-state");
    if (button) {
      button.setAttribute("aria-pressed", resolvedTheme === "dark" ? "true" : "false");
      button.setAttribute("aria-label", normalizedPreference === "auto"
        ? `切换主题，当前跟随系统(${resolvedTheme === "dark" ? "夜间" : "日间"})`
        : `切换主题，当前${resolvedTheme === "dark" ? "夜间" : "日间"}`);
    }
    if (state) {
      state.textContent = normalizedPreference === "auto"
        ? "自动"
        : (resolvedTheme === "dark" ? "夜间" : "日间");
    }
    return { preference: normalizedPreference, theme: resolvedTheme };
  }

  function setupThemeToggle() {
    const button = document.getElementById("theme-toggle");
    if (!button) {
      return;
    }

    applyThemePreference(readThemePreference(), { persist: false });

    button.addEventListener("click", () => {
      const currentPreference = readThemePreference();
      const nextPreference = nextThemePreference(currentPreference);
      applyThemePreference(nextPreference, { persist: true });
    });

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleSystemThemeChange = () => {
      if (readThemePreference() === "auto") {
        applyThemePreference("auto", { persist: false });
      }
    };

    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", handleSystemThemeChange);
    } else if (typeof mediaQuery.addListener === "function") {
      mediaQuery.addListener(handleSystemThemeChange);
    }
  }

  function isPlainObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function toFiniteNumber(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function toTimestamp(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    if (typeof value === "number") {
      return Number.isFinite(value) ? value : null;
    }
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function toBoolean(value) {
    if (typeof value === "boolean") {
      return value;
    }
    if (typeof value === "string") {
      const normalized = value.trim().toLowerCase();
      if (normalized === "true") {
        return true;
      }
      if (normalized === "false") {
        return false;
      }
    }
    return Boolean(value);
  }

  function normalizeObjectiveList(items) {
    if (!Array.isArray(items)) {
      return [];
    }
    return items
      .map((item) => toFiniteNumber(item))
      .filter((item) => item !== null);
  }

  function normalizeControl(control) {
    if (!isPlainObject(control)) {
      return {
        stop_requested: false,
        reason: "",
        requested_at: null,
        requested_at_iso: null,
      };
    }
    return {
      stop_requested: toBoolean(control.stop_requested),
      reason: control.reason || "",
      requested_at: control.requested_at ?? null,
      requested_at_iso: control.requested_at_iso ?? null,
    };
  }

  function normalizeCurvePoints(points, fallbackKey) {
    if (!Array.isArray(points)) {
      return [];
    }

    return points
      .map((point) => {
        if (!isPlainObject(point)) {
          return null;
        }
        const freq = toFiniteNumber(point.freq);
        if (freq === null) {
          return null;
        }

        const normalized = { ...point, freq };
        ["s11", "s12", "s21", "value"].forEach((key) => {
          if (point[key] === undefined) {
            return;
          }
          const numeric = toFiniteNumber(point[key]);
          normalized[key] = numeric === null ? point[key] : numeric;
        });

        const candidateKeys = [fallbackKey, "s11", "s12", "s21", "value"];
        const hasValue = candidateKeys.some((key) => normalized[key] !== undefined && normalized[key] !== null);
        if (!hasValue) {
          return null;
        }
        if (normalized[fallbackKey] === undefined && normalized.value !== undefined) {
          normalized[fallbackKey] = normalized.value;
        }
        return normalized;
      })
      .filter(Boolean);
  }

  function normalizeCurveCollection(curves, fallbackKey) {
    if (!isPlainObject(curves)) {
      return { threshold: null, best: [], last: [] };
    }
    return {
      threshold: curves.threshold ?? null,
      best: normalizeCurvePoints(curves.best, fallbackKey),
      last: normalizeCurvePoints(curves.last, fallbackKey),
    };
  }

  function normalizeStage(stage) {
    if (!isPlainObject(stage)) {
      return {};
    }
    return {
      ...stage,
      s12_threshold: stage.s12_threshold ?? stage.s21_threshold ?? null,
      s21_threshold: stage.s21_threshold ?? stage.s12_threshold ?? null,
    };
  }

  function normalizeS11Profile(profile) {
    if (!isPlainObject(profile)) {
      return null;
    }

    const edgePoints = Array.isArray(profile.edge_points)
      ? profile.edge_points
        .map((item) => {
          if (!isPlainObject(item)) {
            return null;
          }
          const freq = toFiniteNumber(item.freq);
          const threshold = toFiniteNumber(item.threshold);
          if (freq === null || threshold === null) {
            return null;
          }
          return { freq, threshold };
        })
        .filter(Boolean)
      : [];

    return {
      interior_threshold: toFiniteNumber(profile.interior_threshold ?? profile.default_threshold),
      freq_tolerance: toFiniteNumber(profile.freq_tolerance) ?? 1e-6,
      edge_points: edgePoints,
    };
  }

  function getS11ThresholdAtFreq(freq, profile, fallbackThreshold) {
    const normalized = normalizeS11Profile(profile);
    const fallback = toFiniteNumber(fallbackThreshold);
    if (!normalized) {
      return fallback;
    }

    const numericFreq = toFiniteNumber(freq);
    if (numericFreq === null) {
      return fallback;
    }

    for (const item of normalized.edge_points) {
      if (Math.abs(numericFreq - item.freq) <= normalized.freq_tolerance) {
        return item.threshold;
      }
    }

    return normalized.interior_threshold ?? fallback;
  }

  function buildS11ThresholdSeries(points, profile, fallbackThreshold, band = null) {
    const source = Array.isArray(points) ? points : [];
    if (!source.length) {
      return [];
    }

    const bandMin = Array.isArray(band) && band.length >= 1 ? toFiniteNumber(band[0]) : null;
    const bandMax = Array.isArray(band) && band.length >= 2 ? toFiniteNumber(band[1]) : null;

    return source
      .map((point) => ({
        freq: point.freq,
        threshold: getS11ThresholdAtFreq(point.freq, profile, fallbackThreshold),
      }))
      .filter((item) => Number.isFinite(item.threshold))
      .filter((item) => {
        if (bandMin === null || bandMax === null) {
          return true;
        }
        return item.freq >= bandMin && item.freq <= bandMax;
      });
  }

  function describeS11ThresholdProfile(profile, fallbackThreshold, band) {
    const normalized = normalizeS11Profile(profile);
    const fallback = toFiniteNumber(fallbackThreshold);
    if (!normalized) {
      return fallback !== null ? `${formatNumber(fallback)} dB` : "N/A";
    }

    if (!normalized.edge_points.length) {
      if (normalized.interior_threshold !== null && normalized.interior_threshold !== undefined) {
        return `${formatNumber(normalized.interior_threshold)} dB`;
      }
      return fallback !== null ? `${formatNumber(fallback)} dB` : "N/A";
    }

    const edgeFreqs = normalized.edge_points.map((item) => item.freq);
    const edgeThreshold = normalized.edge_points[0].threshold;
    const interiorThreshold = normalized.interior_threshold ?? fallback;

    if (edgeFreqs.length >= 2 && interiorThreshold !== null && interiorThreshold !== undefined) {
      const edgeMin = Math.min(...edgeFreqs);
      const edgeMax = Math.max(...edgeFreqs);
      const bandStart = Array.isArray(band) && band.length >= 1 ? Number(band[0]) : edgeMin;
      const bandEnd = Array.isArray(band) && band.length >= 2 ? Number(band[1]) : edgeMax;
      const innerStart = Math.min(Math.max(edgeMin + 1, bandStart), bandEnd);
      const innerEnd = Math.max(Math.min(edgeMax - 1, bandEnd), bandStart);
      return `${formatNumber(edgeMin, 0)}/${formatNumber(edgeMax, 0)} GHz ${formatNumber(edgeThreshold)} dB, ${formatNumber(innerStart, 0)}-${formatNumber(innerEnd, 0)} GHz ${formatNumber(interiorThreshold)} dB`;
    }

    if (interiorThreshold !== null && interiorThreshold !== undefined) {
      return `${normalized.edge_points.length} edge points @ ${formatNumber(edgeThreshold)} dB, interior ${formatNumber(interiorThreshold)} dB`;
    }

    return `${normalized.edge_points.length} edge points @ ${formatNumber(edgeThreshold)} dB`;
  }

  function normalizeHistory(history, optimizationMode) {
    if (!Array.isArray(history)) {
      return [];
    }

    return history
      .map((item, index) => {
        if (!isPlainObject(item)) {
          return null;
        }
        const simId = toFiniteNumber(item.sim_id ?? index + 1);
        const iterId = toFiniteNumber(item.iter_id ?? item.iter);
        const fitness = toFiniteNumber(item.fitness);
        if (simId === null || fitness === null) {
          return null;
        }

        return {
          ...item,
          sim_id: simId,
          iter_id: iterId,
          fitness,
          objectives: optimizationMode === "multi_objective" ? normalizeObjectiveList(item.objectives) : [],
          constraint_violation: optimizationMode === "multi_objective" ? toFiniteNumber(item.constraint_violation) : null,
        };
      })
      .filter(Boolean);
  }

  function normalizeParetoFront(points) {
    if (!Array.isArray(points)) {
      return [];
    }

    return points
      .map((point) => {
        if (!isPlainObject(point)) {
          return null;
        }
        const objectives = normalizeObjectiveList(point.objectives);
        if (objectives.length < 1) {
          return null;
        }
        return {
          ...point,
          objectives,
          constraint_violation: toFiniteNumber(point.constraint_violation),
        };
      })
      .filter(Boolean);
  }

  function inferOptimizationMode(explicitMode, target, paretoFront, objectives) {
    if (explicitMode === "multi_objective" || explicitMode === "single_objective") {
      return explicitMode;
    }
    if (target?.multi_objective?.enabled === true) {
      return "multi_objective";
    }
    if (Array.isArray(paretoFront) && paretoFront.length > 0) {
      return "multi_objective";
    }
    if (Array.isArray(objectives) && objectives.length >= 2) {
      return "multi_objective";
    }
    return "single_objective";
  }

  function normalizeDashboardState(state) {
    const source = isPlainObject(state) ? state : sampleState;
    const currentRaw = isPlainObject(source.current) ? source.current : {};
    const targetRaw = isPlainObject(source.target) ? source.target : {};
    const statusRaw = isPlainObject(source.status) ? source.status : {};
    const controlRaw = isPlainObject(source.control) ? source.control : {};
    const metricsRaw = isPlainObject(source.metrics) ? source.metrics : {};
    const metaRaw = isPlainObject(source.meta) ? source.meta : {};
    const runtimeRaw = isPlainObject(source.runtime) ? source.runtime : {};
    const algorithmRaw = isPlainObject(source.algorithm) ? source.algorithm : {};
    const s11Curves = normalizeCurveCollection(source.s11Curves, "s11");
    const normalizedS12Curves = normalizeCurveCollection(source.s12Curves, "s12");
    const normalizedS21Curves = normalizeCurveCollection(source.s21Curves, "s21");
    const pointingErrorCurves = normalizeCurveCollection(source.pointingErrorCurves, "value");
    const mergedS12Curves = (normalizedS12Curves.best.length || normalizedS12Curves.last.length)
      ? {
        ...normalizedS12Curves,
        threshold: normalizedS12Curves.threshold ?? targetRaw.s12_threshold ?? targetRaw.s21_threshold ?? null,
      }
      : {
        threshold: normalizedS21Curves.threshold ?? targetRaw.s12_threshold ?? targetRaw.s21_threshold ?? null,
        best: normalizedS21Curves.best,
        last: normalizedS21Curves.last,
      };
    const objectives = normalizeObjectiveList(currentRaw.objectives);
    const paretoFront = normalizeParetoFront(source.paretoFront);
    const target = {
      ...targetRaw,
      multi_objective: isPlainObject(targetRaw.multi_objective) ? targetRaw.multi_objective : {},
      s11_profile: normalizeS11Profile(targetRaw.s11_profile),
      s12_threshold: targetRaw.s12_threshold ?? targetRaw.s21_threshold ?? null,
      s21_threshold: targetRaw.s21_threshold ?? targetRaw.s12_threshold ?? null,
      stages: Array.isArray(targetRaw.stages) ? targetRaw.stages.map(normalizeStage) : [],
    };
    const optimizationMode = inferOptimizationMode(source.optimization_mode, target, paretoFront, objectives);

    return {
      ...source,
      title: source.title || "Optimization Dashboard",
      subtitle: source.subtitle || "",
      mode: source.mode || "Static preview",
      meta: {
        source_name: metaRaw.source_name || source.source_name || "N/A",
        task_name: metaRaw.task_name || source.task_name || "N/A",
      },
      optimization_mode: optimizationMode,
      status: {
        label: statusRaw.label || "N/A",
        tone: statusRaw.tone || "running",
        detail: statusRaw.detail || "",
      },
      control: normalizeControl(controlRaw),
      runtime: {
        run_started_at: runtimeRaw.run_started_at || null,
        finished_at: runtimeRaw.finished_at || null,
        active_sim_started_at: runtimeRaw.active_sim_started_at || null,
        active_sim_id: toFiniteNumber(runtimeRaw.active_sim_id ?? currentRaw.active_sim_id),
        active_iter_id: toFiniteNumber(runtimeRaw.active_iter_id ?? currentRaw.active_iter_id),
        completed_simulations: toFiniteNumber(runtimeRaw.completed_simulations ?? currentRaw.sim_id),
        max_simulations: toFiniteNumber(runtimeRaw.max_simulations ?? algorithmRaw.max_simulations),
        progress_fraction: toFiniteNumber(runtimeRaw.progress_fraction),
        progress_percent: toFiniteNumber(runtimeRaw.progress_percent),
        total_runtime_seconds: toFiniteNumber(runtimeRaw.total_runtime_seconds),
        total_runtime_display: runtimeRaw.total_runtime_display || currentRaw.elapsed || "N/A",
        current_sim_runtime_seconds: toFiniteNumber(runtimeRaw.current_sim_runtime_seconds),
        current_sim_runtime_display: runtimeRaw.current_sim_runtime_display || "N/A",
        last_sim_runtime_seconds: toFiniteNumber(runtimeRaw.last_sim_runtime_seconds),
        last_sim_runtime_display: runtimeRaw.last_sim_runtime_display || "N/A",
      },
      algorithm: {
        method: algorithmRaw.method || source.method || null,
        population_size: toFiniteNumber(algorithmRaw.population_size),
        max_iterations: toFiniteNumber(algorithmRaw.max_iterations),
        max_simulations: toFiniteNumber(algorithmRaw.max_simulations ?? runtimeRaw.max_simulations),
        history_loaded: toFiniteNumber(algorithmRaw.history_loaded),
      },
      current: {
        ...currentRaw,
        sim_id: toFiniteNumber(currentRaw.sim_id),
        iter_id: toFiniteNumber(currentRaw.iter_id ?? currentRaw.iter),
        checkpoint: toBoolean(currentRaw.checkpoint),
        elapsed: currentRaw.elapsed || "N/A",
        component_costs: isPlainObject(currentRaw.component_costs) ? currentRaw.component_costs : {},
        raw_metrics: isPlainObject(currentRaw.raw_metrics) ? currentRaw.raw_metrics : {},
        adaptive_scales: isPlainObject(currentRaw.adaptive_scales) ? currentRaw.adaptive_scales : {},
        extra_metrics: isPlainObject(currentRaw.extra_metrics) ? currentRaw.extra_metrics : {},
        objectives: optimizationMode === "multi_objective" ? objectives : [],
        constraint_violation: optimizationMode === "multi_objective" ? toFiniteNumber(currentRaw.constraint_violation) : null,
      },
      metrics: metricsRaw,
      s11Curves,
      s12Curves: mergedS12Curves,
      s21Curves: normalizedS21Curves,
      pointingErrorCurves,
      target,
      parameters: Array.isArray(source.parameters) ? source.parameters : [],
      fitnessHistory: normalizeHistory(source.fitnessHistory, optimizationMode),
      paretoFront: optimizationMode === "multi_objective" ? paretoFront : [],
      events: Array.isArray(source.events) ? source.events : [],
    };
  }

  function hasCurveContent(dataset) {
    return Boolean((dataset?.best || []).length || (dataset?.last || []).length);
  }

  function signalLabel(valueKey) {
    switch (valueKey) {
      case "s21":
        return "S21";
      case "s12":
        return "S12";
      default:
        return "S11";
    }
  }

  function formatDurationClock(totalSeconds) {
    if (totalSeconds === null || totalSeconds === undefined || Number.isNaN(Number(totalSeconds))) {
      return "N/A";
    }
    const whole = Math.max(Math.floor(Number(totalSeconds)), 0);
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    const seconds = whole % 60;
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }

  function statusToneClass(tone) {
    switch (tone) {
      case "success":
        return "pill-success";
      case "paused":
        return "pill-paused";
      case "failed":
        return "pill-failed";
      default:
        return "pill-running";
    }
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function getCurveDataset(state, candidates, defaultValueKey = "s11") {
    const curveKeys = Array.isArray(candidates) ? candidates : [candidates];
    for (const key of curveKeys) {
      const curves = state?.[key];
      const best = Array.isArray(curves?.best) ? curves.best : [];
      const last = Array.isArray(curves?.last) ? curves.last : [];
      if (!best.length && !last.length) {
        continue;
      }

      const samplePoint = best[0] || last[0] || {};
      const valueKey = [defaultValueKey, "s21", "s12", "s11"].find((candidate) => samplePoint[candidate] !== undefined) || defaultValueKey;
      return {
        threshold: curves?.threshold ?? null,
        best,
        last,
        valueKey,
      };
    }

    return {
      threshold: null,
      best: [],
      last: [],
      valueKey: defaultValueKey,
    };
  }

  function renderSummaryMetric(metric, label, valueClass = "") {
    return `
      <div class="summary-stat">
        <div class="summary-stat-label">${escapeHtml(label)}</div>
        <div class="summary-stat-value ${valueClass}">${escapeHtml(metric?.value ?? "N/A")}</div>
        <div class="summary-stat-meta">${escapeHtml(metric?.note ?? "")}</div>
      </div>
    `;
  }

  function renderSummaryRow({ label, value = "N/A", meta = "", valueClass = "", valueHtml = "" }) {
    const renderedValue = valueHtml || escapeHtml(value ?? "N/A");
    return `
      <div class="summary-row">
        <div class="summary-row-copy">
          <div class="summary-row-label">${escapeHtml(label)}</div>
          <div class="summary-row-meta">${escapeHtml(meta)}</div>
        </div>
        <div class="summary-row-value ${valueClass}">${renderedValue}</div>
      </div>
    `;
  }

  function renderSummaryRuntimeRow({
    label,
    role,
    value = "N/A",
    meta = "",
    valueClass = "",
    startedAt = null,
    finishedAt = null,
    fallbackSeconds = null,
  }) {
    const startedAtAttr = startedAt ? ` data-started-at="${escapeHtml(String(startedAt))}"` : "";
    const finishedAtAttr = finishedAt ? ` data-finished-at="${escapeHtml(String(finishedAt))}"` : "";
    const fallbackSecondsAttr = fallbackSeconds !== null && fallbackSeconds !== undefined
      ? ` data-fallback-seconds="${escapeHtml(String(fallbackSeconds))}"`
      : "";
    return renderSummaryRow({
      label,
      meta,
      valueClass,
      valueHtml: `<span data-runtime-role="${escapeHtml(role)}"${startedAtAttr}${finishedAtAttr}${fallbackSecondsAttr}>${escapeHtml(value)}</span>`,
    });
  }

  function isMultiObjective(state) {
    return state?.optimization_mode === "multi_objective";
  }

  function getObjectiveDefinitions(state) {
    const definitions = state?.target?.multi_objective?.objectives;
    return Array.isArray(definitions) ? definitions.filter((item) => isPlainObject(item)) : [];
  }

  function getObjectiveLabel(state, index) {
    const definition = getObjectiveDefinitions(state)[index];
    return definition?.name || definition?.type || `objective_${index + 1}`;
  }

  function getObjectiveCount(state) {
    const definitionCount = getObjectiveDefinitions(state).length;
    const currentCount = Array.isArray(state?.current?.objectives) ? state.current.objectives.length : 0;
    const historyCount = Array.isArray(state?.fitnessHistory)
      ? state.fitnessHistory.reduce(
          (count, item) => Math.max(count, Array.isArray(item?.objectives) ? item.objectives.length : 0),
          0,
        )
      : 0;
    return Math.max(definitionCount, currentCount, historyCount);
  }

  function getCurrentPeakLossMetric(state) {
    const worst = state?.current?.extra_metrics?.far_field?.summary?.worst_peak_loss_db;
    const freq = state?.current?.extra_metrics?.far_field?.summary?.worst_peak_loss_frequency;
    if (worst === null || worst === undefined || Number.isNaN(Number(worst))) {
      return { value: "N/A", note: "当前 peak_loss 最差点" };
    }
    return {
      value: `${formatNumber(worst, 3)} dB`,
      note: freq ? `worst @ ${freq}` : "当前 peak_loss 最差点",
    };
  }

  function getCurrentPointingErrorMetric(state) {
    const worst = state?.current?.extra_metrics?.far_field?.summary?.worst_pointing_error_deg;
    const freq = state?.current?.extra_metrics?.far_field?.summary?.worst_pointing_error_frequency;
    if (worst === null || worst === undefined || Number.isNaN(Number(worst))) {
      return { value: "N/A", note: "当前 pointing error 最差点" };
    }
    return {
      value: `${formatNumber(worst, 3)} deg`,
      note: freq ? `worst @ ${freq}` : "当前 pointing error 最差点",
    };
  }

  function getParetoFrontSize(state) {
    return Array.isArray(state?.paretoFront) ? state.paretoFront.length : 0;
  }

  function getSimulationProgress(state) {
    const completed = toFiniteNumber(state?.runtime?.completed_simulations ?? state?.current?.sim_id) ?? 0;
    const activeSimId = toFiniteNumber(state?.runtime?.active_sim_id);
    const maxSimulations = toFiniteNumber(state?.runtime?.max_simulations ?? state?.algorithm?.max_simulations);
    const inFlight = activeSimId !== null && activeSimId > completed;
    let fraction = toFiniteNumber(state?.runtime?.progress_fraction);
    if (fraction === null && maxSimulations && maxSimulations > 0) {
      fraction = clamp(completed / maxSimulations, 0, 1);
    }
    return {
      completed,
      maxSimulations,
      activeSimId,
      inFlight,
      fraction,
      percent: fraction === null ? null : fraction * 100,
    };
  }

  function renderSimulationProgress(progress) {
    const maxLabel = progress.maxSimulations !== null ? String(progress.maxSimulations) : "N/A";
    const completedLabel = String(progress.completed ?? 0);
    const percentLabel = progress.percent !== null ? `${formatNumber(progress.percent, 1)}%` : "N/A";
    const width = progress.fraction !== null ? `${Math.max(progress.fraction * 100, 2)}%` : "8%";
    const trackClass = progress.fraction !== null ? "" : " progress-track--indeterminate";
    const meta = progress.inFlight
      ? `已完成 ${completedLabel} 次，sim_id ${progress.activeSimId} 正在运行`
      : `已完成 ${completedLabel} 次评估`;
    return {
      meta,
      valueHtml: `
        <div class="progress-stack">
          <div class="progress-head">
            <span class="progress-count mono">${escapeHtml(completedLabel)} / ${escapeHtml(maxLabel)}</span>
            <span class="progress-percent mono">${escapeHtml(percentLabel)}</span>
          </div>
          <div class="progress-track${trackClass}">
            <div class="progress-fill" style="width: ${escapeHtml(width)}"></div>
          </div>
        </div>
      `,
    };
  }

  function renderOverviewItem(label, value, meta = "", valueClass = "") {
    return `
      <article class="overview-item">
        <div class="overview-label">${escapeHtml(label)}</div>
        <div class="overview-value ${valueClass}">${escapeHtml(value ?? "N/A")}</div>
        <div class="overview-meta">${escapeHtml(meta)}</div>
      </article>
    `;
  }

  function renderTimerOverviewItem({ label, role, value, meta = "", valueClass = "", startedAt = null, finishedAt = null, fallbackSeconds = null }) {
    const startedAtAttr = startedAt ? ` data-started-at="${escapeHtml(String(startedAt))}"` : "";
    const finishedAtAttr = finishedAt ? ` data-finished-at="${escapeHtml(String(finishedAt))}"` : "";
    const fallbackSecondsAttr = fallbackSeconds !== null && fallbackSeconds !== undefined ? ` data-fallback-seconds="${escapeHtml(String(fallbackSeconds))}"` : "";
    return `
      <article class="overview-item">
        <div class="overview-label">${escapeHtml(label)}</div>
        <div class="overview-value ${valueClass}" data-runtime-role="${escapeHtml(role)}"${startedAtAttr}${finishedAtAttr}${fallbackSecondsAttr}>${escapeHtml(value ?? "N/A")}</div>
        <div class="overview-meta">${escapeHtml(meta)}</div>
      </article>
    `;
  }

  let runtimeTickerId = null;

  function stopRuntimeTicker() {
    if (runtimeTickerId !== null) {
      window.clearInterval(runtimeTickerId);
      runtimeTickerId = null;
    }
  }

  function refreshRuntimeLabels() {
    const labels = document.querySelectorAll("[data-runtime-role]");
    labels.forEach((node) => {
      const role = node.getAttribute("data-runtime-role");
      const startedAt = toTimestamp(node.getAttribute("data-started-at"));
      const finishedAt = toTimestamp(node.getAttribute("data-finished-at"));
      const fallbackSeconds = toFiniteNumber(node.getAttribute("data-fallback-seconds"));
      if (startedAt !== null) {
        const end = finishedAt !== null ? finishedAt : Date.now();
        const elapsedSeconds = Math.max((end - startedAt) / 1000, 0);
        node.textContent = formatDurationClock(elapsedSeconds);
        return;
      }
      if ((role === "current-sim" || role === "total-runtime") && fallbackSeconds !== null) {
        node.textContent = formatDurationClock(fallbackSeconds);
      }
    });
  }

  function startRuntimeTicker() {
    stopRuntimeTicker();
    refreshRuntimeLabels();
    const hasRunningTimer = document.querySelector('[data-runtime-role][data-started-at]:not([data-finished-at])');
    if (!hasRunningTimer) {
      return;
    }
    runtimeTickerId = window.setInterval(refreshRuntimeLabels, 1000);
  }

  function renderOverviewStrip(state) {
    const strip = document.getElementById("overview-strip");
    if (!strip) {
      return;
    }

    const multiObjective = isMultiObjective(state);
    const current = state.current || {};
    const runtime = state.runtime || {};
    const activeSimId = runtime.active_sim_id ?? current.sim_id;
    const activeIterId = runtime.active_iter_id ?? current.iter_id;
    const isActiveSimulation = Boolean(runtime.active_sim_started_at) && !runtime.finished_at;
    const currentSimLabel = isActiveSimulation ? "本次仿真" : "最近一次仿真";
    const currentSimMeta = isActiveSimulation
      ? `sim_id ${activeSimId ?? "N/A"} / iter ${activeIterId ?? "N/A"}`
      : `sim_id ${current.sim_id ?? "N/A"} / iter ${current.iter_id ?? "N/A"}`;
    const currentSimValue = isActiveSimulation
      ? (runtime.current_sim_runtime_display || "00:00:00")
      : (runtime.last_sim_runtime_display || "N/A");

    const cells = [
      renderOverviewItem(
        "当前迭代",
        `${current.sim_id ?? "N/A"} / ${current.iter_id ?? "N/A"}`,
        "sim_id / iter_id",
        "mono",
      ),
      `
        <article class="overview-item">
          <div class="overview-label">运行状态</div>
          <div class="overview-value"><span class="pill ${statusToneClass(state.status?.tone || "running")}">${escapeHtml(state.status?.label ?? "N/A")}</span></div>
          <div class="overview-meta">${escapeHtml(state.status?.detail || "当前任务状态")}</div>
        </article>
      `,
      renderTimerOverviewItem({
        label: currentSimLabel,
        role: "current-sim",
        value: currentSimValue,
        meta: currentSimMeta,
        valueClass: "mono",
        startedAt: isActiveSimulation ? runtime.active_sim_started_at : null,
        finishedAt: runtime.finished_at,
        fallbackSeconds: isActiveSimulation ? runtime.current_sim_runtime_seconds : runtime.last_sim_runtime_seconds,
      }),
      renderTimerOverviewItem({
        label: "总运行时间",
        role: "total-runtime",
        value: runtime.total_runtime_display || current.elapsed || "N/A",
        meta: multiObjective ? "run start -> latest snapshot" : "run start -> final snapshot",
        valueClass: "mono",
        startedAt: runtime.run_started_at,
        finishedAt: runtime.finished_at,
        fallbackSeconds: runtime.total_runtime_seconds,
      }),
    ];

    strip.innerHTML = cells.join("");
    startRuntimeTicker();
  }

  function renderSummary(state) {
    const summaryGrid = document.getElementById("summary-grid");
    if (!summaryGrid) {
      return;
    }

    const multiObjective = isMultiObjective(state);
    const current = state.current || {};
    const runtime = state.runtime || {};
    const targetBand = state.target?.freq_band || null;
    const s11Curves = getCurveDataset(state, ["s11Curves"], "s11");
    const s12Curves = getCurveDataset(state, ["s12Curves", "s21Curves"], "s12");
    const bestWorstS11 = getBandWorstMetric(s11Curves.best || [], targetBand, "s11");
    const lastWorstS11 = getBandWorstMetric(s11Curves.last || [], targetBand, "s11");
    const bestWorstS21 = getBandWorstMetric(s12Curves.best || [], targetBand, s12Curves.valueKey);
    const lastWorstS21 = getBandWorstMetric(s12Curves.last || [], targetBand, s12Curves.valueKey);
    const s11Threshold = state.target?.s11_threshold;
    const s11Profile = state.target?.s11_profile;
    const s11ThresholdDisplay = describeS11ThresholdProfile(s11Profile, s11Threshold, state.target?.freq_band);
    const s12Threshold = state.target?.s12_threshold ?? state.target?.s21_threshold;
    const hasSecondarySignal = hasCurveContent(s12Curves) || (s12Threshold !== undefined && s12Threshold !== null);
    const secondarySignalLabel = signalLabel(s12Curves.valueKey);
    const peakLossThreshold = state.target?.multi_objective?.peak_loss_threshold;
    const currentObjectives = Array.isArray(state.current?.objectives) ? state.current.objectives : [];
    const objectiveSummaryRows = Array.from({ length: getObjectiveCount(state) }, (_, index) => renderSummaryRow({
      label: getObjectiveLabel(state, index),
      meta: `representative ${getObjectiveLabel(state, index)}`,
      value: formatNumber(currentObjectives[index], 3),
      valueClass: "mono",
    })).join("");
    const currentPeakLoss = getCurrentPeakLossMetric(state);
    const currentPointingError = getCurrentPointingErrorMetric(state);
    const frontSize = getParetoFrontSize(state);
    const simProgress = getSimulationProgress(state);
    const simProgressRow = renderSimulationProgress(simProgress);
    const fitnessMetric = formatMetric(state.metrics?.fitness);
    const algorithmMethod = String(state.algorithm?.method || "N/A");
    const isBoMethod = algorithmMethod.toLowerCase() === "bo";
    const boDiagnostics = isPlainObject(current.extra_metrics?.bo_diagnostics) ? current.extra_metrics.bo_diagnostics : {};
    const boSummary = isPlainObject(boDiagnostics.summary) ? boDiagnostics.summary : {};
    const boHistoryLoaded = toFiniteNumber(state.algorithm?.history_loaded ?? boSummary.history_loaded) ?? 0;
    const boPhaseMap = {
      seed: "SEED",
      initial: "INITIAL",
      bo: "BO",
      fallback: "FALLBACK",
    };
    const boPhase = boDiagnostics.phase ? (boPhaseMap[String(boDiagnostics.phase).toLowerCase()] || String(boDiagnostics.phase).toUpperCase()) : "N/A";
    const boObservations = toFiniteNumber(boSummary.observations);
    const boMaeValue = toFiniteNumber(boSummary.mae);
    const bestFitnessValue = toFiniteNumber(state.metrics?.best_fitness?.value ?? state.metrics?.fitness?.value);
    const boMaePercentValue = boMaeValue !== null && bestFitnessValue !== null && Math.abs(bestFitnessValue) > 1e-12
      ? (boMaeValue / Math.abs(bestFitnessValue)) * 100.0
      : null;
    const boMaeDisplay = boMaePercentValue !== null ? `${formatNumber(boMaePercentValue, 1)}%` : "N/A";
    const boMaeMeta = boObservations !== null && boObservations > 0
      ? `relative to best cost, ${boObservations} BO points`
      : "waiting for BO observations";
    const stages = Array.isArray(state.target?.stages) ? state.target.stages : [];
    const bandLabel = formatBand(state.target?.freq_band);
    const bandwidthTarget = state.target?.bandwidth_target !== null && state.target?.bandwidth_target !== undefined
      ? `${formatNumber(state.target.bandwidth_target)} GHz`
      : "N/A";
    const stageCount = String(stages.length || 1);
    const stopRequested = Boolean(state.control?.stop_requested);
    const stopRequestedAt = state.control?.requested_at_iso || state.control?.requested_at || null;
    const stopButtonLabel = stopRequested ? "已请求终止" : "请求终止";
    const stopButtonDisabled = stopRequested || Boolean(runtime.finished_at);
    const stopButtonMeta = stopRequestedAt
      ? `requested @ ${stopRequestedAt}`
      : "点击后在当前仿真完成后安全停止";
    const stopButtonHtml = `
      <button type="button" class="action-button ${stopRequested ? "action-button--armed" : ""}" ${stopButtonDisabled ? "disabled" : ""} data-stop-run-button="1">
        ${escapeHtml(stopButtonLabel)}
      </button>
    `;
    const activeSimId = runtime.active_sim_id ?? current.sim_id;
    const activeIterId = runtime.active_iter_id ?? current.iter_id;
    const isActiveSimulation = Boolean(runtime.active_sim_started_at) && !runtime.finished_at;
    const currentSimLabel = isActiveSimulation ? "本次仿真" : "最近一次仿真";
    const currentSimMeta = isActiveSimulation
      ? `sim_id ${activeSimId ?? "N/A"} / iter ${activeIterId ?? "N/A"}`
      : `sim_id ${current.sim_id ?? "N/A"} / iter ${current.iter_id ?? "N/A"}`;
    const currentSimValue = isActiveSimulation
      ? (runtime.current_sim_runtime_display || "00:00:00")
      : (runtime.last_sim_runtime_display || "N/A");
    const runStatusHtml = `<span class="pill ${statusToneClass(state.status?.tone || "running")}">${escapeHtml(state.status?.label ?? "N/A")}</span>`;
    const taskType = state.task_type || "opt";
    const bestFitnessMetric = formatMetric(state.metrics?.best_fitness);
    const currentFitnessMetric = formatMetric(state.metrics?.current_fitness);

    if (taskType === "sweep") {
      const sweepValue = current.value !== null && current.value !== undefined ? formatNumber(current.value, 4) : "N/A";
      const sweepPointLabel = current.sweep_variable ? `${current.sweep_variable} = ${sweepValue}` : sweepValue;
      summaryGrid.innerHTML = `
        <article class="card summary-card">
          <div class="summary-label">运行概览</div>
          <div class="summary-rows">
            ${renderSummaryRow({ label: "运行状态", meta: state.status?.detail || "当前任务状态", valueHtml: runStatusHtml })}
            ${renderSummaryRow({ label: "当前扫描点", meta: "variable = value", value: sweepPointLabel, valueClass: "mono" })}
            ${renderSummaryRow({ label: "仿真进度", meta: simProgressRow.meta, valueHtml: simProgressRow.valueHtml })}
            ${renderSummaryRuntimeRow({ label: currentSimLabel, role: "current-sim", value: currentSimValue, meta: currentSimMeta, valueClass: "mono", startedAt: isActiveSimulation ? runtime.active_sim_started_at : null, finishedAt: runtime.finished_at, fallbackSeconds: isActiveSimulation ? runtime.current_sim_runtime_seconds : runtime.last_sim_runtime_seconds })}
            ${renderSummaryRuntimeRow({ label: "总运行时间", role: "total-runtime", value: runtime.total_runtime_display || current.elapsed || "N/A", meta: runtime.finished_at ? "run start -> final snapshot" : "run start -> latest snapshot", valueClass: "mono", startedAt: runtime.run_started_at, finishedAt: runtime.finished_at, fallbackSeconds: runtime.total_runtime_seconds })}
            ${renderSummaryRow({ label: "任务终止", meta: stopButtonMeta, valueHtml: stopButtonHtml })}
          </div>
        </article>
        <article class="card summary-card">
          <div class="summary-label">扫描设置</div>
          <div class="summary-rows">
            ${renderSummaryRow({ label: "扫描变量", meta: "configured variables", value: (state.parameters || []).map((item) => item.name).filter(Boolean).join(", ") || "N/A" })}
            ${renderSummaryRow({ label: "分析频段", meta: `${(state.parameters || []).length || 0} variables`, value: bandLabel })}
            ${renderSummaryRow({ label: "S11 阈值", meta: "band max gate", value: s11ThresholdDisplay })}
            ${hasSecondarySignal ? renderSummaryRow({ label: `${secondarySignalLabel} 阈值`, meta: "secondary gate", value: s12Threshold !== undefined && s12Threshold !== null ? `${formatNumber(s12Threshold)} dB` : "N/A" }) : ""}
          </div>
        </article>
        <article class="card summary-card">
          <div class="summary-label">扫描结果</div>
          <div class="summary-rows">
            ${renderSummaryRow({ label: "历史最佳 S11", meta: bestWorstS11.note, value: bestWorstS11.value, valueClass: "summary-accent" })}
            ${renderSummaryRow({ label: "最近一次 S11", meta: lastWorstS11.note, value: lastWorstS11.value, valueClass: "summary-accent" })}
            ${hasSecondarySignal ? renderSummaryRow({ label: `历史最佳 ${secondarySignalLabel}`, meta: bestWorstS21.note, value: bestWorstS21.value }) : renderSummaryRow({ label: "最佳扫描指标", meta: bestFitnessMetric.note || "best task metric", value: bestFitnessMetric.value, valueClass: "mono" })}
            ${hasSecondarySignal ? renderSummaryRow({ label: `最近一次 ${secondarySignalLabel}`, meta: lastWorstS21.note, value: lastWorstS21.value }) : renderSummaryRow({ label: "最近扫描指标", meta: currentFitnessMetric.note || "latest task metric", value: currentFitnessMetric.value, valueClass: "mono" })}
          </div>
        </article>
      `;
      startRuntimeTicker();
      return;
    }

    if (taskType === "val") {
      summaryGrid.innerHTML = `
        <article class="card summary-card">
          <div class="summary-label">运行概览</div>
          <div class="summary-rows">
            ${renderSummaryRow({ label: "运行状态", meta: state.status?.detail || "当前任务状态", valueHtml: runStatusHtml })}
            ${renderSummaryRow({ label: "当前案例", meta: "case name", value: current.case_name || "N/A", valueClass: "mono" })}
            ${renderSummaryRow({ label: "仿真进度", meta: simProgressRow.meta, valueHtml: simProgressRow.valueHtml })}
            ${renderSummaryRuntimeRow({ label: currentSimLabel, role: "current-sim", value: currentSimValue, meta: currentSimMeta, valueClass: "mono", startedAt: isActiveSimulation ? runtime.active_sim_started_at : null, finishedAt: runtime.finished_at, fallbackSeconds: isActiveSimulation ? runtime.current_sim_runtime_seconds : runtime.last_sim_runtime_seconds })}
            ${renderSummaryRuntimeRow({ label: "总运行时间", role: "total-runtime", value: runtime.total_runtime_display || current.elapsed || "N/A", meta: runtime.finished_at ? "run start -> final snapshot" : "run start -> latest snapshot", valueClass: "mono", startedAt: runtime.run_started_at, finishedAt: runtime.finished_at, fallbackSeconds: runtime.total_runtime_seconds })}
            ${renderSummaryRow({ label: "任务终止", meta: stopButtonMeta, valueHtml: stopButtonHtml })}
          </div>
        </article>
        <article class="card summary-card">
          <div class="summary-label">验证目标</div>
          <div class="summary-rows">
            ${renderSummaryRow({ label: "案例总数", meta: "configured validation cases", value: simProgress.maxSimulations !== null ? String(simProgress.maxSimulations) : "N/A", valueClass: "mono" })}
            ${renderSummaryRow({ label: "分析频段", meta: "target band", value: bandLabel })}
            ${renderSummaryRow({ label: "S11 阈值", meta: "band max gate", value: s11ThresholdDisplay })}
            ${hasSecondarySignal ? renderSummaryRow({ label: `${secondarySignalLabel} 阈值`, meta: "secondary gate", value: s12Threshold !== undefined && s12Threshold !== null ? `${formatNumber(s12Threshold)} dB` : "N/A" }) : ""}
          </div>
        </article>
        <article class="card summary-card">
          <div class="summary-label">验证结果</div>
          <div class="summary-rows">
            ${renderSummaryRow({ label: "当前 cost", meta: currentFitnessMetric.note || "latest task metric", value: currentFitnessMetric.value, valueClass: "mono" })}
            ${renderSummaryRow({ label: "最佳 cost", meta: bestFitnessMetric.note || "best task metric", value: bestFitnessMetric.value, valueClass: "mono" })}
            ${renderSummaryRow({ label: "历史最佳 S11", meta: bestWorstS11.note, value: bestWorstS11.value, valueClass: "summary-accent" })}
            ${renderSummaryRow({ label: "最近一次 S11", meta: lastWorstS11.note, value: lastWorstS11.value, valueClass: "summary-accent" })}
          </div>
        </article>
      `;
      startRuntimeTicker();
      return;
    }

    if (multiObjective) {
      summaryGrid.innerHTML = `
        <article class="card summary-card">
          <div class="summary-label">运行概览</div>
          <div class="summary-rows">
            ${renderSummaryRow({
              label: "运行状态",
              meta: state.status?.detail || "当前任务状态",
              valueHtml: runStatusHtml,
            })}
            ${renderSummaryRow({
              label: "当前迭代",
              meta: "sim_id / iter_id",
              value: `${current.sim_id ?? "N/A"} / ${current.iter_id ?? "N/A"}`,
              valueClass: "mono",
            })}
            ${renderSummaryRow({
              label: "仿真进度",
              meta: simProgressRow.meta,
              valueHtml: simProgressRow.valueHtml,
            })}
            ${renderSummaryRuntimeRow({
              label: currentSimLabel,
              role: "current-sim",
              value: currentSimValue,
              meta: currentSimMeta,
              valueClass: "mono",
              startedAt: isActiveSimulation ? runtime.active_sim_started_at : null,
              finishedAt: runtime.finished_at,
              fallbackSeconds: isActiveSimulation ? runtime.current_sim_runtime_seconds : runtime.last_sim_runtime_seconds,
            })}
            ${renderSummaryRuntimeRow({
              label: "总运行时间",
              role: "total-runtime",
              value: runtime.total_runtime_display || current.elapsed || "N/A",
              meta: runtime.finished_at ? "run start -> final snapshot" : "run start -> latest snapshot",
              valueClass: "mono",
              startedAt: runtime.run_started_at,
              finishedAt: runtime.finished_at,
              fallbackSeconds: runtime.total_runtime_seconds,
            })}
            ${renderSummaryRow({
              label: "任务终止",
              meta: stopButtonMeta,
              valueHtml: stopButtonHtml,
            })}
          </div>
        </article>

        <article class="card summary-card">
          <div class="summary-label">目标信息</div>
          <div class="summary-rows">
            ${renderSummaryRow({
              label: "Algorithm",
              meta: "optimization method",
              value: algorithmMethod.toUpperCase(),
              valueClass: "mono",
            })}
            ${renderSummaryRow({
              label: "优化模式",
              meta: "front search",
              value: "多目标 / Pareto",
            })}
            ${renderSummaryRow({
              label: "优化频段",
              meta: `${stageCount} stages`,
              value: bandLabel,
            })}
            ${renderSummaryRow({
              label: "S11 阈值",
              meta: "main return loss gate",
              value: s11ThresholdDisplay,
            })}
            ${renderSummaryRow({
              label: "pointing_error 阈值",
              meta: "multi-objective constraint",
              value: state.target?.multi_objective?.pointing_error_threshold !== undefined && state.target?.multi_objective?.pointing_error_threshold !== null
                ? `${formatNumber(state.target.multi_objective.pointing_error_threshold, 3)} deg`
                : (peakLossThreshold !== undefined && peakLossThreshold !== null ? `${formatNumber(peakLossThreshold, 3)} dB` : "N/A"),
            })}
          </div>
        </article>

        <article class="card summary-card">
          <div class="summary-label">结果摘要</div>
          <div class="summary-rows">
            ${renderSummaryRow({
              label: "Pareto front",
              meta: "当前非支配解数量",
              value: String(frontSize),
              valueClass: "mono",
            })}
            ${renderSummaryRow({
              label: "constraint",
              meta: "当前代表解约束违规",
              value: formatNumber(state.current?.constraint_violation, 4),
              valueClass: "mono",
            })}
            ${objectiveSummaryRows}
            ${renderSummaryRow({
              label: "最差 S11",
              meta: bestWorstS11.note,
              value: bestWorstS11.value,
              valueClass: "summary-accent",
            })}
            ${renderSummaryRow({
              label: "最差 pointing_error",
              meta: currentPointingError.note,
              value: currentPointingError.value,
              valueClass: "summary-accent",
            })}
            ${renderSummaryRow({
              label: "最差 peak_loss",
              meta: currentPeakLoss.note,
              value: currentPeakLoss.value,
              valueClass: "summary-muted",
            })}
          </div>
        </article>
      `;
      startRuntimeTicker();
      return;
    }

    summaryGrid.innerHTML = `
      <article class="card summary-card">
        <div class="summary-label">运行概览</div>
        <div class="summary-rows">
          ${renderSummaryRow({
            label: "运行状态",
            meta: state.status?.detail || "当前任务状态",
            valueHtml: runStatusHtml,
          })}
          ${renderSummaryRow({
            label: "当前迭代",
            meta: "sim_id / iter_id",
            value: `${current.sim_id ?? "N/A"} / ${current.iter_id ?? "N/A"}`,
            valueClass: "mono",
          })}
          ${renderSummaryRow({
            label: "仿真进度",
            meta: simProgressRow.meta,
            valueHtml: simProgressRow.valueHtml,
          })}
          ${renderSummaryRuntimeRow({
            label: currentSimLabel,
            role: "current-sim",
            value: currentSimValue,
            meta: currentSimMeta,
            valueClass: "mono",
            startedAt: isActiveSimulation ? runtime.active_sim_started_at : null,
            finishedAt: runtime.finished_at,
            fallbackSeconds: isActiveSimulation ? runtime.current_sim_runtime_seconds : runtime.last_sim_runtime_seconds,
          })}
          ${renderSummaryRuntimeRow({
            label: "总运行时间",
            role: "total-runtime",
            value: runtime.total_runtime_display || current.elapsed || "N/A",
            meta: runtime.finished_at ? "run start -> final snapshot" : "run start -> latest snapshot",
            valueClass: "mono",
            startedAt: runtime.run_started_at,
            finishedAt: runtime.finished_at,
            fallbackSeconds: runtime.total_runtime_seconds,
          })}
          ${renderSummaryRow({
            label: "任务终止",
            meta: stopButtonMeta,
            valueHtml: stopButtonHtml,
          })}
        </div>
      </article>

      <article class="card summary-card">
        <div class="summary-label">目标信息</div>
        <div class="summary-rows">
          ${renderSummaryRow({
            label: "Algorithm",
            meta: "optimization method",
            value: algorithmMethod.toUpperCase(),
            valueClass: "mono",
          })}
          ${renderSummaryRow({
            label: "优化模式",
            meta: "single objective",
            value: "单目标 / Fitness",
          })}
          ${renderSummaryRow({
            label: "优化频段",
            meta: `${stageCount} stages`,
            value: bandLabel,
          })}
          ${renderSummaryRow({
            label: "带宽目标",
            meta: "target bandwidth",
            value: bandwidthTarget,
          })}
          ${renderSummaryRow({
            label: "S11 阈值",
            meta: "main return loss gate",
            value: s11ThresholdDisplay,
          })}
          ${hasSecondarySignal
            ? renderSummaryRow({
              label: `${secondarySignalLabel} 阈值`,
              meta: "secondary gate",
              value: s12Threshold !== undefined && s12Threshold !== null ? `${formatNumber(s12Threshold)} dB` : "N/A",
            })
            : ""}
        </div>
      </article>

      <article class="card summary-card">
        <div class="summary-label">结果摘要</div>
        <div class="summary-rows">
          ${renderSummaryRow({
            label: "历史最佳 S11",
            meta: bestWorstS11.note,
            value: bestWorstS11.value,
            valueClass: "summary-accent",
          })}
          ${renderSummaryRow({
            label: "最近一次 S11",
            meta: lastWorstS11.note,
            value: lastWorstS11.value,
            valueClass: "summary-accent",
          })}
          ${hasSecondarySignal
            ? renderSummaryRow({
              label: `历史最佳 ${secondarySignalLabel}`,
              meta: bestWorstS21.note,
              value: bestWorstS21.value,
            })
            : renderSummaryRow({
              label: "历史最佳 fitness",
              meta: fitnessMetric.note || "best fitness",
              value: fitnessMetric.value,
              valueClass: "mono",
            })}
          ${hasSecondarySignal
            ? renderSummaryRow({
              label: `最近一次 ${secondarySignalLabel}`,
              meta: lastWorstS21.note,
              value: lastWorstS21.value,
            })
            : renderSummaryRow({
              label: "当前 fitness",
              meta: fitnessMetric.note || "current fitness",
              value: fitnessMetric.value,
              valueClass: "mono",
            })}
          ${isBoMethod
            ? renderSummaryRow({
              label: "BO Phase",
              meta: "current BO stage",
              value: boPhase,
              valueClass: "mono",
            })
            : ""}
          ${isBoMethod
            ? renderSummaryRow({
              label: "History Loaded",
              meta: "compatible BO history points",
              value: formatNumber(boHistoryLoaded, 0),
              valueClass: "mono",
            })
            : ""}
          ${isBoMethod
            ? renderSummaryRow({
              label: "BO MAE %",
              meta: boMaeMeta,
              value: boMaeDisplay,
              valueClass: "mono",
            })
            : ""}
        </div>
      </article>
    `;
    startRuntimeTicker();
  }

  function collectParamColumns(parameters) {
    const priority = [
      "name",
      "value",
      "min",
      "max",
      "unit",
      "mode",
      "step",
      "count",
      "resolution",
      "constraint",
      "state",
    ];
    const keys = new Set();
    parameters.forEach((item) => {
      Object.keys(item || {}).forEach((key) => keys.add(key));
    });

    const extras = [...keys].filter((key) => !priority.includes(key)).sort();
    return [...priority.filter((key) => keys.has(key)), ...extras];
  }

  function formatParamHeader(key) {
    const labels = {
      name: "名称",
      value: "当前值",
      min: "最小值",
      max: "最大值",
      unit: "单位",
      mode: "模式",
      step: "步进",
      count: "数量",
      resolution: "精度",
      constraint: "约束",
      state: "状态",
    };
    return labels[key] || key.toUpperCase();
  }

  function renderParameterTable(parameters) {
    const table = document.getElementById("param-table");
    if (!parameters || parameters.length === 0) {
      table.innerHTML = '<tr><td class="chart-empty">暂无参数数据</td></tr>';
      return;
    }

    const columns = collectParamColumns(parameters);
    const headers = columns.map((key) => `<th>${escapeHtml(formatParamHeader(key))}</th>`).join("");
    const rows = parameters
      .map((param) => {
        const cells = columns
          .map((key) => {
            const raw = param[key];
            if (key === "name") {
              return `<td><span class="param-name">${escapeHtml(raw)}</span></td>`;
            }
            if (key === "constraint") {
              return `<td>${raw ? `<span class="pill pill-paused mono">${escapeHtml(raw)}</span>` : "N/A"}</td>`;
            }
            if (key === "state") {
              const normalized = raw ? String(raw).toUpperCase() : "N/A";
              const tone = String(raw).toLowerCase() === "active" ? "pill-running" : "pill-paused";
              return `<td><span class="pill ${tone}">${escapeHtml(normalized)}</span></td>`;
            }
            if (key === "value" || key === "min" || key === "max" || key === "step" || key === "resolution") {
              return `<td class="mono">${escapeHtml(formatValue(raw, key))}</td>`;
            }
            if (key === "count") {
              return `<td class="mono">${raw ?? "N/A"}</td>`;
            }
            return `<td>${escapeHtml(formatValue(raw, key))}</td>`;
          })
          .join("");
        return `<tr>${cells}</tr>`;
      })
      .join("");

    table.innerHTML = `<thead><tr>${headers}</tr></thead><tbody>${rows}</tbody>`;
  }

  function renderStatus(state) {
    const stack = document.getElementById("status-stack");
    if (!stack) {
      return;
    }
    const current = state.current || {};
    const runtime = state.runtime || {};
    const multiObjective = isMultiObjective(state);
    const fitnessMetric = formatMetric(state.metrics?.fitness);
    const objectives = Array.isArray(current.objectives) ? current.objectives : [];
    const frontSize = getParetoFrontSize(state);
    const lastSimRuntime = runtime.last_sim_runtime_display || "N/A";
    const totalRuntime = runtime.total_runtime_display || current.elapsed || "N/A";
    if (multiObjective) {
      const objectiveCount = getObjectiveCount(state);
      const objectiveRows = Array.from({ length: objectiveCount }, (_, index) => `
        <div class="kv-row">
          <div class="kv-label">${escapeHtml(getObjectiveLabel(state, index))}</div>
          <div class="kv-value mono">${escapeHtml(formatNumber(objectives[index], 4))}</div>
        </div>
      `).join("");
      stack.innerHTML = `
        <div class="kv-row">
          <div class="kv-label">Pareto front</div>
          <div class="kv-value mono">${escapeHtml(frontSize)}</div>
        </div>
        <div class="kv-row">
          <div class="kv-label">constraint</div>
          <div class="kv-value mono">${escapeHtml(formatNumber(current.constraint_violation, 4))}</div>
        </div>
        ${objectiveRows}
        <div class="kv-row">
          <div class="kv-label">本次仿真</div>
          <div class="kv-value mono">${escapeHtml(lastSimRuntime)}</div>
        </div>
        <div class="kv-row">
          <div class="kv-label">总运行时间</div>
          <div class="kv-value mono">${escapeHtml(totalRuntime)}</div>
        </div>
      `;
      return;
    }
    stack.innerHTML = `
      <div class="kv-row">
        <div class="kv-label">阶段</div>
        <div class="kv-value mono">${escapeHtml(current.stage || "N/A")}</div>
      </div>
      <div class="kv-row">
        <div class="kv-label">checkpoint</div>
        <div class="kv-value mono">${escapeHtml(current.checkpoint ? "True" : "False")}</div>
      </div>
      <div class="kv-row">
        <div class="kv-label">本次仿真</div>
        <div class="kv-value mono">${escapeHtml(lastSimRuntime)}</div>
      </div>
      <div class="kv-row">
        <div class="kv-label">总运行时间</div>
        <div class="kv-value mono">${escapeHtml(totalRuntime)}</div>
      </div>
      <div class="kv-row">
        <div class="kv-label">当前 fitness</div>
        <div class="kv-value mono">${escapeHtml(fitnessMetric.value || "N/A")}</div>
      </div>
    `;
  }

  function renderTarget(state) {
    const target = document.getElementById("target-list");
    if (!target) {
      return;
    }
    const info = state.target || {};
    const stages = Array.isArray(info.stages) ? info.stages : [];
    const multiObjective = isMultiObjective(state);
    const secondaryCurves = getCurveDataset(state, ["s12Curves", "s21Curves"], "s12");
    const hasSecondarySignal = hasCurveContent(secondaryCurves) || (info.s12_threshold !== undefined && info.s12_threshold !== null);
    const secondarySignalLabel = signalLabel(secondaryCurves.valueKey);
    const pointingErrorThreshold = info.multi_objective?.pointing_error_threshold;
    const peakLossThreshold = info.multi_objective?.peak_loss_threshold;
    const s11ThresholdDisplay = describeS11ThresholdProfile(info.s11_profile, info.s11_threshold, info.freq_band);
    const rows = [
      { label: "优化模式", value: multiObjective ? "多目标 / Pareto" : "单目标 / Fitness" },
      { label: "频段", value: formatBand(info.freq_band) },
      { label: "带宽目标", value: info.bandwidth_target !== null && info.bandwidth_target !== undefined ? `${formatNumber(info.bandwidth_target)} GHz` : "N/A" },
      { label: "S11 阈值", value: s11ThresholdDisplay },
      hasSecondarySignal ? { label: `${secondarySignalLabel} 阈值`, value: info.s12_threshold !== undefined && info.s12_threshold !== null ? `${formatNumber(info.s12_threshold)} dB` : "N/A" } : null,
      multiObjective ? {
        label: pointingErrorThreshold !== null && pointingErrorThreshold !== undefined ? "pointing_error 阈值" : "peak_loss 阈值",
        value: pointingErrorThreshold !== null && pointingErrorThreshold !== undefined
          ? `${formatNumber(pointingErrorThreshold, 3)} deg`
          : (peakLossThreshold !== null && peakLossThreshold !== undefined ? `${formatNumber(peakLossThreshold, 3)} dB` : "N/A"),
      } : null,
      { label: "增益下限", value: info.gain_min !== null && info.gain_min !== undefined ? `${formatNumber(info.gain_min)} dBi` : "N/A" },
      { label: "阶段数", value: stages.length ? String(stages.length) : "1" },
    ].filter(Boolean);

    target.innerHTML =
      rows
        .map(
          (row) => `
          <div class="target-row">
            <div class="target-label">${escapeHtml(row.label)}</div>
            <div class="target-value">${escapeHtml(row.value)}</div>
          </div>
        `,
        )
        .join("");
  }

  function formatCurveSummary(points, valueKey = "s11", options = {}) {
    if (!Array.isArray(points) || points.length === 0) {
      return "N/A";
    }
    const highlightMode = options.highlightMode === "max" ? "max" : "min";
    const unit = options.unit || "dB";
    const focus = points.reduce(
      (currentBest, point) => {
        if (highlightMode === "max") {
          return Number(point[valueKey]) > Number(currentBest[valueKey]) ? point : currentBest;
        }
        return Number(point[valueKey]) < Number(currentBest[valueKey]) ? point : currentBest;
      },
      points[0],
    );
    return `${highlightMode} ${formatNumber(focus[valueKey], 2)} ${unit} @ ${formatNumber(focus.freq, 2)} GHz`;
  }

  function getBandWorstMetric(points, band, valueKey = "s11") {
    const source = Array.isArray(points) ? points : [];
    if (!source.length) {
      return { value: "N/A", note: `目标频段内最大 ${String(valueKey).toUpperCase()}` };
    }

    const inBand = Array.isArray(band) && band.length >= 2
      ? source.filter((point) => Number(point.freq) >= band[0] && Number(point.freq) <= band[1])
      : source;
    const candidates = inBand.length ? inBand : source;
    const worst = candidates.reduce(
      (currentWorst, point) => (Number(point[valueKey]) > Number(currentWorst[valueKey]) ? point : currentWorst),
      candidates[0],
    );

    return {
      value: `${formatNumber(worst[valueKey], 2)} dB`,
      note: `band max @ ${formatNumber(worst.freq, 2)} GHz`,
    };
  }

  function renderCurveChart(container, points, options = {}) {
    if (!container) {
      return;
    }

    const sortedPoints = [...(points || [])].sort((a, b) => a.freq - b.freq);
    if (!sortedPoints.length) {
      container.innerHTML = '<div class="chart-empty">暂无曲线数据</div>';
      return;
    }

    const valueKey = options.valueKey || "s11";
    const unitLabel = options.unitLabel || "dB";
    const highlightMode = options.highlightMode === "max" ? "max" : "min";
    const startColor = options.startColor || themeColor("--chart-best-start", "#ff5f92");
    const endColor = options.endColor || themeColor("--chart-best-end", "#ff9b69");
    const gridStrong = themeColor("--chart-grid-strong", "rgba(255, 194, 148, 0.18)");
    const gridSoft = themeColor("--chart-grid-soft", "rgba(255, 194, 148, 0.08)");
    const thresholdColor = themeColor("--chart-threshold", "rgba(255, 191, 134, 0.92)");
    const thresholdLabelColor = themeColor("--chart-threshold-label", "#ffc48f");
    const axisLabelColor = themeColor("--chart-axis-text", "#a9949b");
    const dotFill = themeColor("--chart-dot-fill", "#140d13");
    const dotStroke = themeColor("--chart-dot-stroke", "#ff7a95");
    const highlightFill = themeColor("--chart-highlight-fill", "#ffbf86");
    const bestLabelColor = themeColor("--chart-best-label", "#ffd8ba");
    const width = 560;
    const height = 248;
    const padding = { left: 56, right: 22, top: 22, bottom: 42 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const xMin = options.xMin ?? sortedPoints[0].freq;
    const xMax = options.xMax ?? sortedPoints[sortedPoints.length - 1].freq;
    const yValues = sortedPoints.map((point) => Number(point[valueKey]));
      const thresholdSeries = buildS11ThresholdSeries(sortedPoints, options.thresholdProfile, options.threshold, [
        options.xMin,
        options.xMax,
      ]);
    const thresholdValues = thresholdSeries.map((item) => Number(item.threshold)).filter((item) => Number.isFinite(item));
    const yMinRaw = Math.min(...yValues, ...(thresholdValues.length ? thresholdValues : [options.threshold ?? Infinity]));
    const yMaxRaw = Math.max(...yValues, ...(thresholdValues.length ? thresholdValues : [options.threshold ?? -Infinity]));
    const yPad = Math.max((yMaxRaw - yMinRaw) * 0.18, 0.8);
    const yMin = yMinRaw - yPad;
    const yMax = yMaxRaw + yPad;
    const xRange = xMax - xMin || 1;
    const yRange = yMax - yMin || 1;

    const xFor = (value) => padding.left + ((value - xMin) / xRange) * plotWidth;
    const yFor = (value) => padding.top + ((yMax - value) / yRange) * plotHeight;

    const pointsWithCoords = sortedPoints.map((point) => ({
      ...point,
      x: xFor(point.freq),
      y: yFor(point[valueKey]),
    }));

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", options.ariaLabel || "S11 frequency chart");
    svg.style.width = "100%";
    svg.style.height = "100%";
    svg.style.display = "block";

    const defs = createSvgNode("defs");
    const gradientId = options.gradientId || "s11-gradient";
    const gradient = createSvgNode("linearGradient", { id: gradientId, x1: "0", x2: "1", y1: "0", y2: "1" });
    gradient.appendChild(createSvgNode("stop", { offset: "0%", "stop-color": startColor }));
    gradient.appendChild(createSvgNode("stop", { offset: "100%", "stop-color": endColor }));
    defs.appendChild(gradient);
    svg.appendChild(defs);

    for (let i = 0; i <= 4; i += 1) {
      const y = padding.top + (plotHeight / 4) * i;
      svg.appendChild(createSvgNode("line", {
        x1: padding.left,
        x2: width - padding.right,
        y1: y,
        y2: y,
        stroke: i === 4 ? gridStrong : gridSoft,
        "stroke-dasharray": i === 4 ? "0" : "5 8",
      }));
    }

      if (thresholdSeries.length) {
        const thresholdPath = thresholdSeries
          .map((point, index) => `${index === 0 ? "M" : "L"} ${xFor(point.freq)} ${yFor(point.threshold)}`)
          .join(" ");
        svg.appendChild(createSvgNode("path", {
          d: thresholdPath,
        fill: "none",
        stroke: thresholdColor,
        "stroke-width": "1.6",
        "stroke-dasharray": "6 6",
      }));

        const labelText = options.thresholdLabel
          || (options.threshold !== undefined && options.threshold !== null
            ? `threshold ${formatNumber(options.threshold, 2)} ${unitLabel}`
            : `threshold profile ${unitLabel}`);
        const lastThreshold = thresholdSeries[thresholdSeries.length - 1];
        const tag = createSvgNode("text", {
          x: width - padding.right - 4,
          y: Math.max(yFor(lastThreshold.threshold) - 6, 18),
        fill: thresholdLabelColor,
        "font-size": "13",
        "text-anchor": "end",
        "font-family": "Cascadia Mono, Consolas, monospace",
      });
      tag.textContent = labelText;
      svg.appendChild(tag);
    } else if (options.threshold !== undefined && options.threshold !== null) {
      const y = yFor(options.threshold);
      svg.appendChild(createSvgNode("line", {
        x1: padding.left,
        x2: width - padding.right,
        y1: y,
        y2: y,
        stroke: thresholdColor,
        "stroke-width": "1.4",
        "stroke-dasharray": "6 6",
      }));

      const tag = createSvgNode("text", {
        x: width - padding.right - 4,
        y: Math.max(y - 6, 18),
        fill: thresholdLabelColor,
        "font-size": "13",
        "text-anchor": "end",
        "font-family": "Cascadia Mono, Consolas, monospace",
      });
      tag.textContent = `threshold ${formatNumber(options.threshold, 2)} ${unitLabel}`;
      svg.appendChild(tag);
    }

    const pathData = pointsWithCoords
      .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
      .join(" ");
    const fillPath =
      `${pathData} L ${pointsWithCoords[pointsWithCoords.length - 1].x} ${height - padding.bottom} ` +
      `L ${pointsWithCoords[0].x} ${height - padding.bottom} Z`;

    svg.appendChild(createSvgNode("path", {
      d: fillPath,
      fill: `url(#${gradientId})`,
      opacity: "0.11",
    }));

    svg.appendChild(createSvgNode("path", {
      d: pathData,
      fill: "none",
      stroke: `url(#${gradientId})`,
      "stroke-width": "4",
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
    }));

    const highlightValue = highlightMode === "max" ? Math.max(...yValues) : Math.min(...yValues);
    pointsWithCoords.forEach((point) => {
      const isBest = point[valueKey] === highlightValue;
      svg.appendChild(createSvgNode("circle", {
        cx: point.x,
        cy: point.y,
        r: isBest ? "5.8" : "4.2",
        fill: isBest ? highlightFill : dotFill,
        stroke: isBest ? highlightFill : dotStroke,
        "stroke-width": "2.4",
      }));
    });

    const xTicks = [xMin, (xMin + xMax) / 2, xMax];
    xTicks.forEach((value) => {
      const x = xFor(value);
      const label = createSvgNode("text", {
        x,
        y: height - 16,
        fill: axisLabelColor,
        "font-size": "13",
        "text-anchor": "middle",
        "font-family": "Cascadia Mono, Consolas, monospace",
      });
      label.textContent = `${formatNumber(value, 0)}`;
      svg.appendChild(label);
    });

    const yTicks = 4;
    for (let i = 0; i <= yTicks; i += 1) {
      const value = yMin + ((yMax - yMin) / yTicks) * i;
      const label = createSvgNode("text", {
        x: 12,
        y: yFor(value) + 4,
        fill: axisLabelColor,
        "font-size": "13",
        "font-family": "Cascadia Mono, Consolas, monospace",
      });
      label.textContent = formatNumber(value, 2);
      svg.appendChild(label);
    }

    const bestPoint = pointsWithCoords.reduce((best, current) => {
      if (highlightMode === "max") {
        return Number(current[valueKey]) > Number(best[valueKey]) ? current : best;
      }
      return Number(current[valueKey]) < Number(best[valueKey]) ? current : best;
    }, pointsWithCoords[0]);
    const bestTag = createSvgNode("text", {
      x: clamp(bestPoint.x + 10, padding.left + 10, width - 140),
      y: clamp(bestPoint.y - 12, 20, height - 18),
      fill: bestLabelColor,
      "font-size": "13",
      "font-family": "Cascadia Mono, Consolas, monospace",
    });
    bestTag.textContent = `${highlightMode} ${formatNumber(bestPoint[valueKey], 2)} ${unitLabel}`;
    svg.appendChild(bestTag);

    container.innerHTML = "";
    container.appendChild(svg);
  }

  function renderCurveComparison(state) {
    const target = state.target || {};
    const container = document.getElementById("curve-grid");
    const panelTitle = document.getElementById("curve-panel-title");
    const panelNote = document.getElementById("curve-panel-note");
    const s11Curves = getCurveDataset(state, ["s11Curves"], "s11");
    const s12Curves = getCurveDataset(state, ["s12Curves", "s21Curves"], "s12");
    const pointingCurves = getCurveDataset(state, ["pointingErrorCurves"], "value");
    const xBand = Array.isArray(target.freq_band) ? target.freq_band : null;
    const curveFamilies = [
      {
        family: "s11",
        label: signalLabel(s11Curves.valueKey),
        dataset: s11Curves,
        range: {
          xMin: xBand ? xBand[0] : ((s11Curves.best.length || s11Curves.last.length) ? Math.min(...[...s11Curves.best, ...s11Curves.last].map((p) => p.freq)) : 0),
          xMax: xBand ? xBand[1] : ((s11Curves.best.length || s11Curves.last.length) ? Math.max(...[...s11Curves.best, ...s11Curves.last].map((p) => p.freq)) : 1),
          threshold: s11Curves.threshold ?? target.s11_threshold ?? null,
          thresholdProfile: target.s11_profile ?? null,
          thresholdLabel: describeS11ThresholdProfile(target.s11_profile, target.s11_threshold, target.freq_band),
          valueKey: s11Curves.valueKey,
          unitLabel: "dB",
          highlightMode: "min",
        },
        colors: {
          best: [themeColor("--chart-best-start", "#ff5f92"), themeColor("--chart-best-end", "#ff9b69")],
          last: [themeColor("--chart-last-start", "#ffb168"), themeColor("--chart-last-end", "#ff7a95")],
        },
        summary: {
          unit: "dB",
          highlightMode: "min",
        },
      },
      {
        family: "s12",
        label: signalLabel(s12Curves.valueKey),
        dataset: s12Curves,
        range: {
          xMin: xBand ? xBand[0] : ((s12Curves.best.length || s12Curves.last.length) ? Math.min(...[...s12Curves.best, ...s12Curves.last].map((p) => p.freq)) : 0),
          xMax: xBand ? xBand[1] : ((s12Curves.best.length || s12Curves.last.length) ? Math.max(...[...s12Curves.best, ...s12Curves.last].map((p) => p.freq)) : 1),
          threshold: s12Curves.threshold ?? target.s12_threshold ?? target.s21_threshold ?? null,
          valueKey: s12Curves.valueKey,
          unitLabel: "dB",
          highlightMode: "min",
        },
        colors: {
          best: [themeColor("--chart-secondary-best-start", "#ff7b9d"), themeColor("--chart-secondary-best-end", "#ffc47f")],
          last: [themeColor("--chart-secondary-last-start", "#ff8f72"), themeColor("--chart-secondary-last-end", "#ffd6a9")],
        },
        summary: {
          unit: "dB",
          highlightMode: "min",
        },
      },
    ];
    if (pointingCurves.best.length || pointingCurves.last.length) {
      curveFamilies.push({
        family: "pointing",
        label: "pointing_error",
        dataset: pointingCurves,
        range: {
          xMin: xBand ? xBand[0] : ((pointingCurves.best.length || pointingCurves.last.length) ? Math.min(...[...pointingCurves.best, ...pointingCurves.last].map((p) => p.freq)) : 0),
          xMax: xBand ? xBand[1] : ((pointingCurves.best.length || pointingCurves.last.length) ? Math.max(...[...pointingCurves.best, ...pointingCurves.last].map((p) => p.freq)) : 1),
          threshold: pointingCurves.threshold ?? target.multi_objective?.pointing_error_threshold ?? null,
          valueKey: pointingCurves.valueKey,
          unitLabel: "deg",
          highlightMode: "max",
        },
        colors: {
          best: [themeColor("--chart-tertiary-best-start", "#6d86c9"), themeColor("--chart-tertiary-best-end", "#60c1b6")],
          last: [themeColor("--chart-tertiary-last-start", "#94a7d8"), themeColor("--chart-tertiary-last-end", "#8fd4cb")],
        },
        summary: {
          unit: "deg",
          highlightMode: "max",
        },
      });
    }

    const panels = [];
    curveFamilies.forEach((familyConfig) => {
      const { family, label, dataset, range, colors, summary } = familyConfig;
      if (dataset.best.length) {
        panels.push({
          id: `${family}-best`,
          title: `最优 ${label}`,
          points: dataset.best,
          valueKey: dataset.valueKey,
          summary,
          options: {
            ...range,
            gradientId: `${family}-best-gradient`,
            startColor: colors.best[0],
            endColor: colors.best[1],
            ariaLabel: `best ${label} frequency chart`,
          },
        });
      }
      if (dataset.last.length) {
        panels.push({
          id: `${family}-last`,
          title: `最近一次 ${label}`,
          points: dataset.last,
          valueKey: dataset.valueKey,
          summary,
          options: {
            ...range,
            gradientId: `${family}-last-gradient`,
            startColor: colors.last[0],
            endColor: colors.last[1],
            ariaLabel: `last ${label} frequency chart`,
          },
        });
      }
    });

    if (panelTitle) {
      panelTitle.textContent = panels.length ? "关键频率曲线对比" : "频率曲线";
    }
    if (panelNote) {
      const hasPointing = panels.some((panel) => panel.title.includes("pointing_error"));
      panelNote.textContent = panels.length
        ? (hasPointing ? "已根据快照自动显示可用的 S 参数与 pointing error 曲线。" : "已根据快照自动显示可用的 S 参数曲线。")
        : "当前快照未提供可绘制的频率曲线。";
    }

    if (!panels.length) {
      container.innerHTML = '<div class="chart-empty curve-empty">暂无频率曲线数据</div>';
      return;
    }

    const wideClass = panels.length === 1 ? " curve-card--wide" : "";
    container.innerHTML = panels
      .map(
        (panel) => `
          <section class="curve-card${wideClass}">
            <div class="curve-head">
              <div>
                <div class="curve-title">${escapeHtml(panel.title)}</div>
                <div class="curve-subtitle" id="${panel.id}-summary"></div>
              </div>
            </div>
            <div class="curve-chart" id="${panel.id}-chart"></div>
          </section>
        `,
      )
      .join("");

    panels.forEach((panel) => {
      const summaryEl = document.getElementById(`${panel.id}-summary`);
      if (summaryEl) {
        summaryEl.textContent = formatCurveSummary(panel.points, panel.valueKey, panel.summary || {});
      }
      renderCurveChart(document.getElementById(`${panel.id}-chart`), panel.points, panel.options);
    });
  }

  function createSvgNode(tag, attrs = {}) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
    return el;
  }

  function buildBestSoFarSeries(history) {
    const items = Array.isArray(history) ? history : [];
    const normalized = items
      .map((point, index) => {
        const simId = Number(point?.sim_id ?? index + 1);
        const fitness = Number(point?.fitness);
        return {
          ...point,
          sim_id: Number.isFinite(simId) ? simId : index + 1,
          fitness: Number.isFinite(fitness) ? fitness : null,
          _order: index,
        };
      })
      .filter((point) => Number.isFinite(point.sim_id) && Number.isFinite(point.fitness))
      .sort((a, b) => a.sim_id - b.sim_id || a._order - b._order);

    let runningBest = Infinity;
    return normalized.map((point) => {
      runningBest = Math.min(runningBest, point.fitness);
      return {
        ...point,
        bestFitness: runningBest,
      };
    });
  }

  function renderChart(state) {
    if (isMultiObjective(state)) {
      if (getObjectiveCount(state) <= 1) {
        renderSingleObjectiveParetoChart(state);
      } else {
        renderParetoChart(state);
      }
      return;
    }
    const container = document.getElementById("fitness-chart");
    const history = Array.isArray(state.fitnessHistory) ? state.fitnessHistory : [];
    if (history.length === 0) {
      container.innerHTML = '<div class="chart-empty">暂无 fitness 历史数据</div>';
      return;
    }

    const width = 1100;
    const height = 420;
    const padding = { left: 64, right: 26, top: 28, bottom: 54 };
    const axisLabelColor = themeColor("--chart-axis-text", "#a9949b");
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const series = buildBestSoFarSeries(history);
    if (series.length === 0) {
      container.innerHTML = '<div class="chart-empty">暂无 fitness 历史数据</div>';
      return;
    }
    const values = series.map((point) => Number(point.bestFitness));
    const minY = Math.min(...values);
    const maxY = Math.max(...values);
    const yPad = Math.max((maxY - minY) * 0.18, 0.3);
    const yMin = minY - yPad;
    const yMax = maxY + yPad;
    const yRange = yMax - yMin || 1;
    const xMin = series[0].sim_id;
    const xMax = series[series.length - 1].sim_id;
    const xRange = xMax - xMin || 1;

    const xFor = (simId) => padding.left + ((simId - xMin) / xRange) * plotWidth;
    const yFor = (value) => padding.top + ((yMax - value) / yRange) * plotHeight;

    const points = series.map((point) => ({
      ...point,
      x: xFor(point.sim_id),
      y: yFor(point.bestFitness),
    }));

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "fitness trend chart");
    svg.classList.add("fitness-svg");
    svg.style.width = "100%";
    svg.style.height = "auto";
    svg.style.display = "block";

    const defs = createSvgNode("defs");
    const gradient = createSvgNode("linearGradient", { id: "fitness-gradient", x1: "0", x2: "1", y1: "0", y2: "1" });
    gradient.appendChild(createSvgNode("stop", { offset: "0%", "stop-color": themeColor("--chart-best-start", "#ff5f92") }));
    gradient.appendChild(createSvgNode("stop", { offset: "100%", "stop-color": themeColor("--chart-best-end", "#ff9b69") }));
    defs.appendChild(gradient);

    const glow = createSvgNode("filter", { id: "fitness-glow", x: "-40%", y: "-40%", width: "180%", height: "180%" });
    glow.appendChild(createSvgNode("feGaussianBlur", { stdDeviation: "4", result: "blur" }));
    const merge = createSvgNode("feMerge");
    merge.appendChild(createSvgNode("feMergeNode", { in: "blur" }));
    merge.appendChild(createSvgNode("feMergeNode", { in: "SourceGraphic" }));
    glow.appendChild(merge);
    defs.appendChild(glow);

    svg.appendChild(defs);

    for (let i = 0; i <= 4; i += 1) {
      const y = padding.top + (plotHeight / 4) * i;
      const grid = createSvgNode("line", {
        x1: padding.left,
        x2: width - padding.right,
        y1: y,
        y2: y,
        stroke: i === 4 ? themeColor("--chart-grid-strong", "rgba(255, 194, 148, 0.18)") : themeColor("--chart-grid-soft", "rgba(255, 194, 148, 0.08)"),
        "stroke-dasharray": i === 4 ? "0" : "6 8",
      });
      svg.appendChild(grid);
    }

    const areaPath = points
      .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
      .join(" ");
    const closedAreaPath =
      `${areaPath} L ${points[points.length - 1].x} ${height - padding.bottom} ` +
      `L ${points[0].x} ${height - padding.bottom} Z`;

    const area = createSvgNode("path", {
      d: closedAreaPath,
      fill: "url(#fitness-gradient)",
      opacity: "0.14",
    });
    svg.appendChild(area);

    const line = createSvgNode("path", {
      d: areaPath,
      fill: "none",
      stroke: "url(#fitness-gradient)",
      "stroke-width": "5",
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      filter: "url(#fitness-glow)",
    });
    svg.appendChild(line);

    points.forEach((point) => {
      const dot = createSvgNode("circle", {
        cx: point.x,
        cy: point.y,
        r: point.sim_id === state.current?.sim_id ? "7" : "5",
        fill: point.sim_id === state.current?.sim_id ? themeColor("--chart-highlight-fill", "#ffbf86") : themeColor("--chart-dot-fill", "#140d13"),
        stroke: point.sim_id === state.current?.sim_id ? themeColor("--chart-highlight-stroke", "#ffbf86") : themeColor("--chart-dot-stroke", "#ff7a95"),
        "stroke-width": "3",
      });
      svg.appendChild(dot);
    });

    const xTicks = buildAdaptiveXAxisTicks(xMin, xMax, plotWidth);
    xTicks.forEach((value) => {
      const x = xFor(value);
      svg.appendChild(createSvgNode("line", {
        x1: x,
        x2: x,
        y1: padding.top,
        y2: height - padding.bottom,
        stroke: themeColor("--chart-grid-vertical", "rgba(255, 153, 133, 0.06)"),
        "stroke-dasharray": "4 8",
      }));
      const label = createSvgNode("text", {
        x,
        y: height - 18,
        fill: axisLabelColor,
        "font-size": "14",
        "text-anchor": "middle",
        "font-family": "Cascadia Mono, Consolas, monospace",
      });
      label.textContent = formatAxisTick(value);
      svg.appendChild(label);
    });

    const yTicks = 4;
    for (let i = 0; i <= yTicks; i += 1) {
      const value = yMin + ((yMax - yMin) / yTicks) * i;
      const y = yFor(value);
      const label = createSvgNode("text", {
        x: 16,
        y: y + 4,
        fill: axisLabelColor,
        "font-size": "14",
        "font-family": "Cascadia Mono, Consolas, monospace",
      });
      label.textContent = formatNumber(value, 2);
      svg.appendChild(label);
    }

    const bestPoint = points.reduce((best, current) => (current.bestFitness < best.bestFitness ? current : best), points[0]);
    const bestLabel = createSvgNode("text", {
      x: clamp(bestPoint.x + 10, padding.left + 10, width - 160),
      y: clamp(bestPoint.y - 14, 24, height - 24),
      fill: themeColor("--chart-best-label", "#ffd8ba"),
      "font-size": "14",
      "font-family": "Cascadia Mono, Consolas, monospace",
    });
    bestLabel.textContent = `best ${formatNumber(bestPoint.bestFitness, 2)}`;
    svg.appendChild(bestLabel);

    container.innerHTML = "";
    container.appendChild(svg);
  }

  function buildSingleObjectiveParetoSeries(history) {
    const items = Array.isArray(history) ? history : [];
    const normalized = items
      .map((point, index) => {
        const simId = toFiniteNumber(point?.sim_id ?? index + 1);
        const objective = toFiniteNumber(point?.objectives?.[0]);
        const violation = toFiniteNumber(point?.constraint_violation);
        if (simId === null || objective === null) {
          return null;
        }
        return {
          ...point,
          sim_id: simId,
          objective,
          constraint_violation: violation,
          feasible: violation !== null && violation <= 1e-12,
          _order: index,
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.sim_id - b.sim_id || a._order - b._order);

    let bestFeasible = null;
    return normalized.map((point) => {
      if (point.feasible) {
        bestFeasible = bestFeasible === null ? point.objective : Math.min(bestFeasible, point.objective);
      }
      return { ...point, bestFeasible };
    });
  }

  function renderSingleObjectiveParetoChart(state) {
    const container = document.getElementById("fitness-chart");
    const series = buildSingleObjectiveParetoSeries(state.fitnessHistory);
    if (!series.length) {
      container.innerHTML = '<div class="chart-empty">暂无 objective 历史数据</div>';
      return;
    }

    const width = 1100;
    const height = 420;
    const padding = { left: 78, right: 30, top: 28, bottom: 58 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const axisLabelColor = themeColor("--chart-axis-text", "#a9949b");
    const objectiveValues = series.map((point) => point.objective);
    const bestValues = series.map((point) => point.bestFeasible).filter((value) => value !== null);
    const values = objectiveValues.concat(bestValues);
    const minY = Math.min(...values);
    const maxY = Math.max(...values);
    const yPad = Math.max((maxY - minY) * 0.18, 0.05);
    const yMin = minY - yPad;
    const yMax = maxY + yPad;
    const yRange = yMax - yMin || 1;
    const xMin = series[0].sim_id;
    const xMax = series[series.length - 1].sim_id;
    const xRange = xMax - xMin || 1;
    const xFor = (simId) => padding.left + ((simId - xMin) / xRange) * plotWidth;
    const yFor = (value) => padding.top + ((yMax - value) / yRange) * plotHeight;

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${getObjectiveLabel(state, 0)} Pareto evolution chart`);
    svg.classList.add("fitness-svg");
    svg.style.width = "100%";
    svg.style.height = "auto";
    svg.style.display = "block";

    for (let i = 0; i <= 4; i += 1) {
      const y = padding.top + (plotHeight / 4) * i;
      svg.appendChild(createSvgNode("line", {
        x1: padding.left,
        x2: width - padding.right,
        y1: y,
        y2: y,
        stroke: i === 4 ? themeColor("--chart-grid-strong", "rgba(255, 194, 148, 0.18)") : themeColor("--chart-grid-soft", "rgba(255, 194, 148, 0.08)"),
        "stroke-dasharray": i === 4 ? "0" : "6 8",
      }));
    }

    const frontPoints = series.filter((point) => point.bestFeasible !== null);
    if (frontPoints.length) {
      const frontPath = frontPoints
        .map((point, index) => `${index === 0 ? "M" : "L"} ${xFor(point.sim_id)} ${yFor(point.bestFeasible)}`)
        .join(" ");
      svg.appendChild(createSvgNode("path", {
        d: frontPath,
        fill: "none",
        stroke: themeColor("--chart-best-end", "#ff9b69"),
        "stroke-width": "4",
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
      }));
    }

    series.forEach((point) => {
      const current = point.sim_id === state.current?.sim_id;
      svg.appendChild(createSvgNode("circle", {
        cx: xFor(point.sim_id),
        cy: yFor(point.objective),
        r: current ? "6.5" : "4.5",
        fill: point.feasible ? themeColor("--chart-highlight-fill", "#ffbf86") : "none",
        stroke: point.feasible ? themeColor("--chart-highlight-stroke", "#ffbf86") : axisLabelColor,
        "stroke-width": current ? "3" : "2",
        opacity: point.feasible ? "1" : "0.58",
      }));
    });

    buildAdaptiveXAxisTicks(xMin, xMax, plotWidth).forEach((value) => {
      const x = xFor(value);
      svg.appendChild(createSvgNode("line", {
        x1: x,
        x2: x,
        y1: padding.top,
        y2: height - padding.bottom,
        stroke: themeColor("--chart-grid-vertical", "rgba(255, 153, 133, 0.06)"),
        "stroke-dasharray": "4 8",
      }));
      const label = createSvgNode("text", {
        x,
        y: height - 18,
        fill: axisLabelColor,
        "font-size": "14",
        "text-anchor": "middle",
        "font-family": "Cascadia Mono, Consolas, monospace",
      });
      label.textContent = formatAxisTick(value);
      svg.appendChild(label);
    });

    for (let i = 0; i <= 4; i += 1) {
      const value = yMin + ((yMax - yMin) / 4) * i;
      const label = createSvgNode("text", {
        x: padding.left - 12,
        y: yFor(value) + 4,
        fill: axisLabelColor,
        "font-size": "14",
        "text-anchor": "end",
        "font-family": "Cascadia Mono, Consolas, monospace",
      });
      label.textContent = formatNumber(value, 3);
      svg.appendChild(label);
    }

    const xLabel = createSvgNode("text", {
      x: width / 2,
      y: height - 4,
      fill: axisLabelColor,
      "font-size": "14",
      "text-anchor": "middle",
      "font-family": "Cascadia Mono, Consolas, monospace",
    });
    xLabel.textContent = "Simulation";
    svg.appendChild(xLabel);

    const yLabel = createSvgNode("text", {
      x: 22,
      y: height / 2,
      fill: axisLabelColor,
      "font-size": "14",
      "text-anchor": "middle",
      "font-family": "Cascadia Mono, Consolas, monospace",
      transform: `rotate(-90 22 ${height / 2})`,
    });
    yLabel.textContent = getObjectiveLabel(state, 0);
    svg.appendChild(yLabel);

    container.innerHTML = "";
    container.appendChild(svg);
  }

  function renderParetoChart(state) {
    const container = document.getElementById("fitness-chart");
    const points = Array.isArray(state.paretoFront) ? state.paretoFront : [];
    if (!points.length) {
      container.innerHTML = '<div class="chart-empty">暂无 Pareto front 数据</div>';
      return;
    }

    const width = 1100;
    const height = 420;
    const padding = { left: 96, right: 34, top: 28, bottom: 58 };
    const axisLabelColor = themeColor("--chart-axis-text", "#a9949b");
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const xs = points.map((point) => Number(point.objectives?.[0]));
    const ys = points.map((point) => Number(point.objectives?.[1] ?? 0));
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    const yMin = Math.min(...ys);
    const yMax = Math.max(...ys);
    const xPad = Math.max((xMax - xMin) * 0.18, 0.05);
    const yPad = Math.max((yMax - yMin) * 0.18, 0.05);
    const sxMin = xMin - xPad;
    const sxMax = xMax + xPad;
    const syMin = yMin - yPad;
    const syMax = yMax + yPad;
    const xRange = sxMax - sxMin || 1;
    const yRange = syMax - syMin || 1;

    const xFor = (value) => padding.left + ((value - sxMin) / xRange) * plotWidth;
    const yFor = (value) => padding.top + ((syMax - value) / yRange) * plotHeight;

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Pareto front chart");
    svg.classList.add("fitness-svg");
    svg.style.width = "100%";
    svg.style.height = "auto";
    svg.style.display = "block";

    for (let i = 0; i <= 4; i += 1) {
      const y = padding.top + (plotHeight / 4) * i;
      svg.appendChild(createSvgNode("line", {
        x1: padding.left,
        x2: width - padding.right,
        y1: y,
        y2: y,
        stroke: i === 4 ? themeColor("--chart-grid-strong", "rgba(255, 194, 148, 0.18)") : themeColor("--chart-grid-soft", "rgba(255, 194, 148, 0.08)"),
        "stroke-dasharray": i === 4 ? "0" : "6 8",
      }));
    }

    for (let i = 0; i <= 4; i += 1) {
      const x = padding.left + (plotWidth / 4) * i;
      svg.appendChild(createSvgNode("line", {
        x1: x,
        x2: x,
        y1: padding.top,
        y2: height - padding.bottom,
        stroke: themeColor("--chart-grid-vertical", "rgba(255, 153, 133, 0.06)"),
        "stroke-dasharray": "4 8",
      }));
    }

    points.forEach((point, index) => {
      const x = xFor(Number(point.objectives?.[0]));
      const y = yFor(Number(point.objectives?.[1] ?? 0));
      svg.appendChild(createSvgNode("circle", {
        cx: x,
        cy: y,
        r: index === 0 ? "7" : "5.5",
        fill: index === 0 ? themeColor("--chart-highlight-fill", "#ffbf86") : themeColor("--chart-dot-fill", "#140d13"),
        stroke: index === 0 ? themeColor("--chart-highlight-stroke", "#ffbf86") : themeColor("--chart-dot-stroke", "#ff7a95"),
        "stroke-width": "3",
      }));
    });

    const xTicks = [sxMin, (sxMin + sxMax) / 2, sxMax];
    xTicks.forEach((value) => {
      const x = xFor(value);
      const label = createSvgNode("text", {
        x,
        y: height - 18,
        fill: axisLabelColor,
        "font-size": "14",
        "text-anchor": "middle",
        "font-family": "Cascadia Mono, Consolas, monospace",
      });
      label.textContent = formatNumber(value, 3);
      svg.appendChild(label);
    });

    const yTicks = 4;
    for (let i = 0; i <= yTicks; i += 1) {
      const value = syMin + ((syMax - syMin) / yTicks) * i;
      const y = yFor(value);
      const label = createSvgNode("text", {
        x: padding.left - 12,
        y: y + 4,
        fill: axisLabelColor,
        "font-size": "14",
        "text-anchor": "end",
        "font-family": "Cascadia Mono, Consolas, monospace",
      });
      label.textContent = formatNumber(value, 3);
      svg.appendChild(label);
    }

    const xLabel = createSvgNode("text", {
      x: width / 2,
      y: height - 4,
      fill: axisLabelColor,
      "font-size": "14",
      "text-anchor": "middle",
      "font-family": "Cascadia Mono, Consolas, monospace",
    });
    xLabel.textContent = getObjectiveLabel(state, 0);
    svg.appendChild(xLabel);

    const yLabel = createSvgNode("text", {
      x: 28,
      y: height / 2,
      fill: axisLabelColor,
      "font-size": "14",
      "text-anchor": "middle",
      "font-family": "Cascadia Mono, Consolas, monospace",
      transform: `rotate(-90 28 ${height / 2})`,
    });
    yLabel.textContent = getObjectiveLabel(state, 1);
    svg.appendChild(yLabel);

    container.innerHTML = "";
    container.appendChild(svg);
  }

  function renderEvents(state) {
    const list = document.getElementById("event-list");
    const events = Array.isArray(state.events) ? state.events : [];
    if (!events.length) {
      list.innerHTML = '<div class="chart-empty">暂无事件</div>';
      return;
    }

    list.innerHTML = events
      .map(
        (event) => `
          <div class="event-row">
            <div>
              <div class="event-time">${escapeHtml(event.time || "N/A")}</div>
              <div class="event-message">${escapeHtml(event.message || "N/A")}</div>
            </div>
            <div class="pill ${event.severity === "success" ? "pill-success" : "pill-running"}">
              ${escapeHtml(event.severity || "info")}
            </div>
          </div>
        `,
      )
      .join("");
  }

  function renderDashboard(state) {
    const normalized = normalizeDashboardState(state || sampleState);
    document.title = normalized.title || "Optimization Dashboard";
    const heroMeta = document.getElementById("dashboard-meta");
    const modePill = document.getElementById("run-mode-pill");
    const runSubtitle = document.getElementById("run-subtitle");
    const taskType = normalized.task_type || "opt";
    const sourceName = normalized.meta?.source_name || normalized.source_name || "N/A";
    const taskName = normalized.meta?.task_name || normalized.task_name || "N/A";
    if (heroMeta) {
      heroMeta.textContent = `源文件: ${sourceName} | task: ${taskName}`;
    }
    if (modePill) {
      modePill.textContent = normalized.mode || "Static preview";
    }
    if (runSubtitle) {
      runSubtitle.textContent = normalized.subtitle || "";
    }
    const trendTitle = document.getElementById("trend-panel-title");
    const trendNote = document.getElementById("trend-panel-note");
    const curvePanelTitle = document.getElementById("curve-panel-title");
    const curvePanelNote = document.getElementById("curve-panel-note");
    if (trendTitle) {
      const objectiveCount = getObjectiveCount(normalized);
      trendTitle.textContent = isMultiObjective(normalized)
        ? (objectiveCount <= 1 ? `${getObjectiveLabel(normalized, 0)} Front Evolution` : "Pareto Front")
        : (taskType === "sweep" ? "Sweep 指标趋势" : (taskType === "val" ? "Validation 指标趋势" : "Fitness 随仿真次数变化"));
    }
    if (trendNote) {
      const objectiveCount = getObjectiveCount(normalized);
      trendNote.textContent = isMultiObjective(normalized)
        ? (objectiveCount <= 1
          ? "实心点满足硬约束，空心点违反约束；曲线为 best feasible so far。"
          : "非支配解散点图。X/Y 轴对应当前配置的前两个 objective。")
        : (taskType === "sweep" ? "按仿真顺序显示 band max S11 的 best-so-far 曲线。" : (taskType === "val" ? "按案例顺序显示 cost 的 best-so-far 曲线。" : "累计 best-so-far 曲线。"));
    }
    if (curvePanelTitle) {
      curvePanelTitle.textContent = taskType === "val" ? "案例 S 参数对比" : "关键 S 参数对比";
    }
    if (curvePanelNote) {
      curvePanelNote.textContent = taskType === "sweep"
        ? "展示当前最佳点与最近一次扫描点的 S 参数曲线。"
        : (taskType === "val" ? "展示当前最佳案例与最近一次案例的 S 参数曲线。" : "根据快照中可用的曲线自动收缩布局。");
    }

    renderSummary(normalized);
    renderParameterTable(normalized.parameters || []);
    renderCurveComparison(normalized);
    renderChart(normalized);
    renderEvents(normalized);
    bindStopRequestButton(normalized);
  }

  function getTaskDirFromLocation() {
    try {
      const params = new URLSearchParams(window.location.search);
      return params.get("task_dir") || "";
    } catch (error) {
      return "";
    }
  }

  function getStateFileFromLocation() {
    try {
      const params = new URLSearchParams(window.location.search);
      return params.get("state_file") || "";
    } catch (error) {
      return "";
    }
  }

  async function fetchDashboardState({ taskDir = "", stateFile = "" } = {}) {
    const search = new URLSearchParams();
    if (stateFile) {
      search.set("state_file", stateFile);
    } else if (taskDir) {
      search.set("task_dir", taskDir);
    }
    const response = await fetch(`/api/state?${search.toString()}`, {
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`state request failed: ${response.status}`);
    }
    return response.json();
  }

  async function requestOptimizationStop(taskDir) {
    const search = new URLSearchParams();
    if (taskDir) {
      search.set("task_dir", taskDir);
    }
    const response = await fetch(`/api/control/stop?${search.toString()}`, {
      method: "POST",
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`stop request failed: ${response.status}`);
    }
    return response.json();
  }

  function bindStopRequestButton(state) {
    const button = document.querySelector("[data-stop-run-button='1']");
    if (!button) {
      return;
    }

    const runtime = state.runtime || {};
    const taskDir = window.dashboardTaskDir || getTaskDirFromLocation();
    const stopRequested = Boolean(state.control?.stop_requested);
    button.disabled = stopRequested || Boolean(runtime.finished_at) || !taskDir;

    button.addEventListener("click", async () => {
      if (!taskDir) {
        return;
      }
      button.disabled = true;
      const previousLabel = button.textContent;
      button.textContent = "请求中...";
      try {
        await requestOptimizationStop(taskDir);
        const refreshed = await fetchDashboardState({ taskDir });
        window.dashboardSampleState = refreshed;
        renderDashboard({
          ...refreshed,
          mode: "Live polling",
          subtitle: `Watching ${taskDir}`,
        });
      } catch (error) {
        button.textContent = previousLabel;
        button.disabled = false;
      }
    });
  }

  function startLivePolling(taskDir) {
    const modePill = document.getElementById("run-mode-pill");
    const runSubtitle = document.getElementById("run-subtitle");
    const stateUrl = `/api/state?task_dir=${encodeURIComponent(taskDir)}`;
    window.dashboardTaskDir = taskDir;

    if (modePill) {
      modePill.textContent = "Live polling";
    }
    if (runSubtitle) {
      runSubtitle.textContent = `Watching ${taskDir}`;
    }

    const refresh = async () => {
      try {
        const state = await fetchDashboardState({ taskDir });
        window.dashboardSampleState = state;
        renderDashboard({
          ...state,
          mode: "Live polling",
          subtitle: `Watching ${taskDir}`,
        });
      } catch (error) {
        if (runSubtitle) {
          runSubtitle.textContent = `Waiting for state file: ${stateUrl}`;
        }
      }
    };

    refresh();
    window.setInterval(refresh, 2000);
  }

  async function startStaticStateLoad(stateFile) {
    const runSubtitle = document.getElementById("run-subtitle");
    window.dashboardTaskDir = "";
    try {
      const state = await fetchDashboardState({ stateFile });
      window.dashboardSampleState = state;
      renderDashboard({
        ...state,
        mode: "Static JSON",
        subtitle: `Loaded ${stateFile}`,
      });
    } catch (error) {
      if (runSubtitle) {
        runSubtitle.textContent = `Failed to load static state: ${stateFile}`;
      }
      renderDashboard({
        ...sampleState,
        mode: "Static preview",
        subtitle: `Static JSON load failed: ${stateFile}`,
      });
    }
  }

  window.renderOptimizationDashboard = renderDashboard;
  window.dashboardSampleState = sampleState;

  document.addEventListener("DOMContentLoaded", () => {
    const externalState = window.__OPTIMIZER_DASHBOARD_STATE__ || window.dashboardState;
    const stateFile = getStateFileFromLocation();
    const taskDir = getTaskDirFromLocation();
    setupThemeToggle();
    if (stateFile) {
      startStaticStateLoad(stateFile);
      return;
    }
    if (taskDir) {
      startLivePolling(taskDir);
      return;
    }
    renderDashboard(externalState || sampleState);
  });
})();
