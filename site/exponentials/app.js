const state = {
  data: null,
  selected: "all",
};

const chart = document.getElementById("chart");
const select = document.getElementById("fieldSelect");
const latestWeek = document.getElementById("latestWeek");
const latestCount = document.getElementById("latestCount");
const slowDouble = document.getElementById("slowDouble");
const fastDouble = document.getElementById("fastDouble");
const fitNote = document.getElementById("fitNote");
const updatedAt = document.getElementById("updatedAt");

const colors = {
  blue: "#436f9c",
  blueSoft: "rgba(67, 111, 156, 0.92)",
  orange: "#f59e0b",
  black: "#111827",
  paper: "#f6f7f4",
  plot: "#fbfcfa",
  muted: "#66717f",
  grid: "#ffffff",
};

function fmtInt(value) {
  return Number(value).toLocaleString("en-US");
}

function doublingText(years) {
  if (!Number.isFinite(years) || years <= 0) return "n/a";
  const months = years * 12;
  if (years >= 2) return `${Math.round(years)} yrs`;
  if (months >= 1.5) return `${Math.round(months)} months`;
  return `${months.toFixed(1)} months`;
}

function dateAfterWeek(iso) {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 7);
  return date.toISOString().slice(0, 10);
}

function stepX(weeks) {
  return weeks.flatMap((week, index) => [week, dateAfterWeek(weeks[index])]);
}

function stepY(values) {
  return values.flatMap((value) => [value, value]);
}

function yearShapes(weeks) {
  const firstYear = Number(weeks[0].slice(0, 4));
  const lastYear = Number(weeks[weeks.length - 1].slice(0, 4));
  const shapes = [];
  for (let year = firstYear + 1; year <= lastYear; year += 1) {
    shapes.push({
      type: "line",
      xref: "x",
      yref: "paper",
      x0: `${year}-01-01`,
      x1: `${year}-01-01`,
      y0: 0,
      y1: 1,
      line: { color: "#ffffff", width: 1.5 },
      layer: "above",
    });
  }
  return shapes;
}

function quarterTicks(weeks) {
  const ticks = [];
  const text = [];
  const seen = new Set();
  const monthLetters = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
  for (const week of weeks) {
    const date = new Date(`${week}T00:00:00Z`);
    const month = date.getUTCMonth();
    const day = date.getUTCDate();
    if (![0, 2, 5, 8, 11].includes(month) || day > 7) continue;
    const key = `${date.getUTCFullYear()}-${month}`;
    if (seen.has(key)) continue;
    seen.add(key);
    ticks.push(week);
    text.push(monthLetters[month]);
  }
  return { ticks, text };
}

function updateSummary(payload, series) {
  const latestIndex = series.counts.length - 1;
  const slowYears = series.components[0].doubling_time_years;
  const fastYears = series.components[1].doubling_time_years;
  latestWeek.textContent = payload.weeks[latestIndex];
  latestCount.textContent = fmtInt(series.counts[latestIndex]);
  slowDouble.textContent = doublingText(slowYears);
  fastDouble.textContent = doublingText(fastYears);
  fitNote.textContent = `Sequential robust weighted fit: orange is the first slow exponential (${doublingText(slowYears)}); black adds an exponential fit to the residual (${doublingText(fastYears)}).`;
  updatedAt.textContent = `Updated ${payload.generated_at_utc.replace("T", " ").replace("+00:00", " UTC")}`;
}

function render() {
  const payload = state.data;
  const series = payload.series[state.selected];
  const weeks = payload.weeks;
  updateSummary(payload, series);
  const stepWeeks = stepX(weeks);
  const { ticks, text } = quarterTicks(weeks);

  const traces = [
    {
      name: `${series.label} papers`,
      type: "scatter",
      mode: "lines",
      x: stepWeeks,
      y: stepY(series.counts),
      fill: "tozeroy",
      line: { color: colors.blueSoft, width: 0, shape: "hv" },
      fillcolor: colors.blueSoft,
      hovertemplate: "%{x}<br><b>%{y:,}</b> papers<extra></extra>",
    },
    {
      name: "slow",
      type: "scatter",
      mode: "lines",
      x: weeks,
      y: series.slow,
      line: { color: colors.orange, width: 4, dash: "dash" },
      hovertemplate: "slow fit<br><b>%{y:.0f}</b><extra></extra>",
    },
    {
      name: "slow + residual",
      type: "scatter",
      mode: "lines",
      x: weeks,
      y: series.total_fit,
      line: { color: colors.black, width: 4 },
      hovertemplate: "total fit<br><b>%{y:.0f}</b><extra></extra>",
    },
  ];

  const layout = {
    autosize: true,
    paper_bgcolor: colors.paper,
    plot_bgcolor: colors.plot,
    margin: { l: 78, r: 22, t: 48, b: 118 },
    showlegend: false,
    hovermode: "x unified",
    dragmode: "zoom",
    font: {
      family: "Avenir Next, Segoe UI, Helvetica Neue, sans-serif",
      size: 16,
      color: colors.black,
    },
    xaxis: {
      tickmode: "array",
      tickvals: ticks,
      ticktext: text,
      showgrid: false,
      zeroline: false,
      showline: false,
      fixedrange: false,
      range: [weeks[0], dateAfterWeek(weeks[weeks.length - 1])],
      tickfont: { size: 20 },
      rangeselector: {
        x: 0,
        y: 1.08,
        xanchor: "left",
        yanchor: "bottom",
        bgcolor: "rgba(255, 255, 255, 0.84)",
        activecolor: "#dce7ef",
        bordercolor: "#c8d0d7",
        borderwidth: 1,
        font: { size: 13, color: colors.black },
        buttons: [
          { count: 1, label: "1Y", step: "year", stepmode: "backward" },
          { count: 3, label: "3Y", step: "year", stepmode: "backward" },
          { count: 5, label: "5Y", step: "year", stepmode: "backward" },
          { label: "All", step: "all" },
        ],
      },
      rangeslider: {
        visible: true,
        thickness: 0.08,
        bgcolor: "#edf1f2",
        bordercolor: "#c8d0d7",
        borderwidth: 1,
      },
    },
    yaxis: {
      rangemode: "tozero",
      zeroline: false,
      showgrid: false,
      showline: true,
      linecolor: colors.black,
      linewidth: 1,
      ticks: "",
      tickfont: { size: 20 },
      automargin: true,
    },
    shapes: yearShapes(weeks),
  };

  const config = {
    responsive: true,
    displaylogo: false,
    scrollZoom: true,
    modeBarButtonsToRemove: [
      "select2d",
      "lasso2d",
      "toggleSpikelines",
    ],
  };

  Plotly.react(chart, traces, layout, config);
}

async function init() {
  const response = await fetch("./data/series.json", { cache: "no-store" });
  state.data = await response.json();
  const seriesOptions = Object.values(state.data.series).sort((a, b) => {
    if (a.id === "all") return -1;
    if (b.id === "all") return 1;
    return a.label.localeCompare(b.label);
  });
  for (const series of seriesOptions) {
    const option = document.createElement("option");
    option.value = series.id;
    option.textContent = series.id === "all" ? "All math" : `${series.label} (${series.id})`;
    select.append(option);
  }
  select.value = state.selected;
  select.addEventListener("change", () => {
    state.selected = select.value;
    render();
  });
  window.addEventListener("resize", () => Plotly.Plots.resize(chart));
  render();
}

init().catch((error) => {
  document.body.innerHTML = `<pre>${error.stack || error}</pre>`;
});
