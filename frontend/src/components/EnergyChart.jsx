import React, { useMemo } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  TimeScale,
  Filler
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import 'chartjs-adapter-date-fns';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  TimeScale,
  Filler
);

export default function EnergyChart({ history }) {
  const chartData = useMemo(() => {
    if (!history || history.length === 0) return { datasets: [] };

    const recentHistory = history.slice(-48);
    
    return {
      datasets: [
        {
          label: 'Actual HVAC Power',
          data: recentHistory.map(h => ({
            x: new Date(h.sim_time),
            y: h.hvac_power_kw
          })),
          borderColor: '#FF6B1A',
          backgroundColor: (context) => {
            const ctx = context.chart.ctx;
            const gradient = ctx.createLinearGradient(0, 0, 0, 300);
            gradient.addColorStop(0, 'rgba(255, 107, 26, 0.5)');
            gradient.addColorStop(1, 'rgba(255, 107, 26, 0.0)');
            return gradient;
          },
          fill: true,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.4,
          order: 2
        },
        {
          label: 'Baseline (Est)',
          data: recentHistory.map(h => ({
            x: new Date(h.sim_time),
            y: h.hvac_power_kw / (1 - (h.energy_savings_pct || 10) / 100)
          })),
          borderColor: 'rgba(156, 163, 175, 0.5)',
          borderDash: [5, 5],
          backgroundColor: 'transparent',
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.4,
          order: 1
        }
      ]
    };
  }, [history]);

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: {
      duration: 0
    },
    plugins: {
      legend: {
        position: 'top',
        labels: {
          color: '#9CA3AF',
          usePointStyle: true,
          boxWidth: 6
        }
      },
      tooltip: {
        mode: 'index',
        intersect: false,
        backgroundColor: 'rgba(17, 24, 39, 0.9)',
        titleColor: '#fff',
        bodyColor: '#cbd5e1',
        borderColor: 'rgba(255,255,255,0.1)',
        borderWidth: 1
      }
    },
    scales: {
      x: {
        type: 'time',
        time: {
          unit: 'hour',
          displayFormats: {
            hour: 'HH:mm'
          }
        },
        grid: {
          color: 'rgba(255,255,255,0.05)',
          drawBorder: false
        },
        ticks: {
          color: '#6B7280'
        }
      },
      y: {
        title: {
          display: true,
          text: 'Power (kW)',
          color: '#6B7280'
        },
        grid: {
          color: 'rgba(255,255,255,0.05)',
          drawBorder: false
        },
        ticks: {
          color: '#6B7280'
        },
        beginAtZero: true
      }
    },
    interaction: {
      mode: 'nearest',
      axis: 'x',
      intersect: false
    }
  };

  return (
    <div className="glass-card p-4 h-[300px] flex flex-col">
      <h3 className="text-sm font-medium text-gray-400 mb-2">Energy Consumption</h3>
      <div className="flex-grow relative">
        {chartData.datasets.length > 0 ? (
          <Line data={chartData} options={options} />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-gray-500">
            Waiting for data...
          </div>
        )}
      </div>
    </div>
  );
}
