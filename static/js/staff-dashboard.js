(() => {
  "use strict";

  const root = document.getElementById("rosarioWeather");
  if (!root) return;

  const latitude = root.dataset.latitude;
  const longitude = root.dataset.longitude;
  const loading = document.getElementById("weatherLoading");
  const content = document.getElementById("weatherContent");
  const error = document.getElementById("weatherError");
  const refresh = document.getElementById("weatherRefresh");
  const cacheKey = "fmis:rosario-weather:v1";
  const cacheLifetime = 30 * 60 * 1000;

  const weatherCodes = {
    0: ["Clear sky", "bi-sun-fill"],
    1: ["Mostly clear", "bi-sun"],
    2: ["Partly cloudy", "bi-cloud-sun-fill"],
    3: ["Overcast", "bi-clouds-fill"],
    45: ["Foggy", "bi-cloud-fog2-fill"],
    48: ["Foggy", "bi-cloud-fog2-fill"],
    51: ["Light drizzle", "bi-cloud-drizzle-fill"],
    53: ["Drizzle", "bi-cloud-drizzle-fill"],
    55: ["Heavy drizzle", "bi-cloud-drizzle-fill"],
    61: ["Light rain", "bi-cloud-rain-fill"],
    63: ["Rain", "bi-cloud-rain-heavy-fill"],
    65: ["Heavy rain", "bi-cloud-rain-heavy-fill"],
    80: ["Rain showers", "bi-cloud-rain-fill"],
    81: ["Rain showers", "bi-cloud-rain-heavy-fill"],
    82: ["Heavy showers", "bi-cloud-rain-heavy-fill"],
    95: ["Thunderstorms", "bi-cloud-lightning-rain-fill"],
    96: ["Thunderstorms", "bi-cloud-lightning-rain-fill"],
    99: ["Severe thunderstorms", "bi-cloud-lightning-rain-fill"],
  };

  const describe = (code) => weatherCodes[code] || ["Mixed conditions", "bi-cloud-sun"];
  const round = (value) => Math.round(Number(value || 0));

  function render(data, cached = false) {
    const current = data.current;
    const daily = data.daily;
    const condition = describe(current.weather_code);
    const planningWeather = document.getElementById("planningWeatherEvidence");
    document.getElementById("weatherTemperature").textContent = `${round(current.temperature_2m)}°C`;
    document.getElementById("weatherDescription").textContent = condition[0];
    document.getElementById("weatherFeelsLike").textContent = `${round(current.apparent_temperature)}°C`;
    if (planningWeather) {
      planningWeather.textContent = `${round(current.temperature_2m)}°C · ${round(daily.precipitation_probability_max[0])}% rain · ${round(current.relative_humidity_2m)}% humidity`;
    }
    document.getElementById("weatherHumidity").textContent = `${round(current.relative_humidity_2m)}%`;
    document.getElementById("weatherRainChance").textContent = `${round(daily.precipitation_probability_max[0])}%`;
    document.getElementById("weatherWind").textContent = `${round(current.wind_speed_10m)} km/h`;
    document.getElementById("weatherSymbol").innerHTML = `<i class="bi ${condition[1]}"></i>`;

    const updated = new Date(current.time);
    document.getElementById("weatherUpdated").textContent = `${updated.toLocaleTimeString("en-PH", { hour: "numeric", minute: "2-digit" })}${cached ? " (cached)" : ""}`;

    loading.hidden = true;
    error.hidden = true;
    content.hidden = false;
  }

  function getCache() {
    try {
      const cached = JSON.parse(localStorage.getItem(cacheKey));
      return cached && cached.data ? cached : null;
    } catch (_) {
      return null;
    }
  }

  async function loadWeather(force = false) {
    const cached = getCache();
    if (!force && cached && Date.now() - cached.savedAt < cacheLifetime) render(cached.data, true);
    if (force || !cached) {
      content.hidden = true;
      error.hidden = true;
      loading.hidden = false;
    }
    refresh.disabled = true;

    const params = new URLSearchParams({
      latitude,
      longitude,
      current: "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
      daily: "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
      timezone: "Asia/Manila",
      forecast_days: "1",
    });
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(`https://api.open-meteo.com/v1/forecast?${params}`, {
        signal: controller.signal
      });
      if (!response.ok) throw new Error(`Weather API returned ${response.status}`);
      const data = await response.json();
      if (!data.current || !data.daily) throw new Error("Incomplete weather response");
      localStorage.setItem(cacheKey, JSON.stringify({
        savedAt: Date.now(),
        data
      }));
      render(data);
    } catch (_) {
      if (cached) render(cached.data, true);
      else {
        loading.hidden = true;
        content.hidden = true;
        error.hidden = false;
        const planningWeather = document.getElementById("planningWeatherEvidence");
        if (planningWeather) planningWeather.textContent = "Live forecast temporarily unavailable";
      }
    } finally {
      window.clearTimeout(timeout);
      refresh.disabled = false;
    }
  }

  refresh.addEventListener("click", () => loadWeather(true));
  loadWeather();
})();
