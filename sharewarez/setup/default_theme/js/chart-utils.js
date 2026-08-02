/**
 * Creates a new Chart.js chart instance.
 * @param {string} canvasId - The ID of the canvas element.
 * @param {string} chartType - The type of chart (e.g., 'bar', 'pie', 'line').
 * @param {object} chartData - The data object for the chart.
 * @param {object} chartOptions - The options object for the chart.
 * @returns {Chart|null} The new Chart instance, or null if the canvas element is not found.
 */
function createChart(canvasId, chartType, chartData, chartOptions) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) {
        console.error(`Canvas element with ID '${canvasId}' not found.`);
        return null;
    }

    const themeOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { labels: { color: 'rgba(225, 229, 245, 0.78)' } },
            title: { color: 'rgba(235, 240, 255, 0.96)', font: { weight: '600' } }
        },
        scales: {
            x: {
                ticks: { color: 'rgba(205, 214, 235, 0.62)' },
                grid: { color: 'rgba(255, 255, 255, 0.06)' }
            },
            y: {
                ticks: { color: 'rgba(205, 214, 235, 0.62)' },
                grid: { color: 'rgba(255, 255, 255, 0.06)' }
            }
        }
    };

    return new Chart(ctx.getContext('2d'), {
        type: chartType,
        data: chartData,
        options: {
            ...themeOptions,
            ...chartOptions,
            plugins: {
                ...themeOptions.plugins,
                ...chartOptions.plugins,
                title: { ...themeOptions.plugins.title, ...chartOptions.plugins?.title }
            },
            scales: {
                ...themeOptions.scales,
                ...chartOptions.scales,
                x: { ...themeOptions.scales.x, ...chartOptions.scales?.x },
                y: { ...themeOptions.scales.y, ...chartOptions.scales?.y }
            }
        }
    });
}
