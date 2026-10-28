import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  componentDidCatch(error, errorInfo) {
    console.error("React Error Boundary caught error:", error, errorInfo);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-[#0A0E1A] text-gray-200 flex flex-col items-center justify-center p-6 text-center">
          <div className="bg-[#111827] border border-red-500/30 rounded-xl p-8 max-w-md shadow-2xl">
            <div className="w-12 h-12 bg-red-500/20 text-red-400 rounded-full flex items-center justify-center mx-auto mb-4 text-2xl font-bold">
              !
            </div>
            <h2 className="text-xl font-bold text-white mb-2">Dashboard Error</h2>
            <p className="text-sm text-gray-400 mb-6">
              The dashboard encountered an unexpected rendering error. Live simulation control continues running in the background.
            </p>
            <button
              onClick={() => window.location.reload()}
              className="bg-[#FF6B1A] hover:bg-[#e05a10] text-white px-5 py-2.5 rounded-lg font-medium text-sm transition-colors shadow-lg shadow-[#FF6B1A]/20"
            >
              Reload Dashboard
            </button>
            {this.state.error && (
              <details className="mt-6 text-left">
                <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-400">Technical Details</summary>
                <pre className="mt-2 text-[11px] font-mono text-red-300/80 bg-black/40 p-3 rounded overflow-x-auto">
                  {this.state.error.toString()}
                </pre>
              </details>
            )}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
