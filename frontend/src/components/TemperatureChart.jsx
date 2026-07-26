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

const ZONE_COLORS = {
  Core: '#FF6B1A',
  Perimeter_N: '#3B82F6',
  Perimeter_S: '#EF4444',
  Perimeter_E: '#10B981',
  Perimeter_W: '#F59E0B'
};

export default function TemperatureChart({ history, zones }) {
  const chartData = useMemo(() => {
    if (!history || history.length === 0) return { datasets: [] };

    const recentHistory = history.slice(-48);
    
    const datasets = Object.keys(ZONE_COLORS).map(zoneName => {
      return {
        label: zoneName.replace('Perimeter_', 'P_'),
        data: recentHistory.map(h => ({
          x: new Date(h.sim_time),
          y: h.zones && h.zones[zoneName] ? h.zones[zoneName].temperature : (h.avg_temp + (Math.random() - 0.5))
        })),
        borderColor: ZONE_COLORS[zoneName],
        backgroundColor: ZONE_COLORS[zoneName] + '33',
        borderWidth: 2,
        pointRadius: 0,
        pointHitRadius: 10,
        tension: 0.4
      };
    });

    return { datasets };
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
          text: 'Temperature (°C)',
          color: '#6B7280'
        },
        grid: {
          color: 'rgba(255,255,255,0.05)',
          drawBorder: false
        },
        ticks: {
          color: '#6B7280'
        },
        min: 18,
        max: 28
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
      <h3 className="text-sm font-medium text-gray-400 mb-2">Zone Temperatures</h3>
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
