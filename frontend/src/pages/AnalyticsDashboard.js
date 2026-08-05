import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line
} from 'recharts';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8000';

export const AnalyticsDashboard = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const response = await axios.get(`${BACKEND_URL}/api/metrics/dashboard`);
        setData(response.data);
      } catch (err) {
        console.error("Failed to load metrics", err);
      } finally {
        setLoading(false);
      }
    };
    fetchMetrics();
  }, []);

  if (loading) {
    return (
      <div className="civic-app min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-xl text-civic-blue font-semibold">Cargando métricas...</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="civic-app min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-xl text-civic-red font-semibold">Error al cargar métricas.</div>
      </div>
    );
  }

  return (
    <div className="civic-app min-h-screen bg-gray-50 p-8">
      <div className="max-w-6xl mx-auto space-y-8">
        
        <header className="flex justify-between items-center mb-12">
          <div>
            <h1 className="text-4xl font-bold text-civic-ink mb-2">Panel de Analíticas</h1>
            <p className="text-gray-600">Métricas de uso y visitas de la plataforma.</p>
          </div>
          <div className="bg-white px-6 py-4 rounded-xl shadow-sm border border-gray-100 flex items-center space-x-4">
            <span className="text-sm text-gray-500 font-medium uppercase tracking-wider">Visitas Totales</span>
            <span className="text-3xl font-bold text-civic-blue">{data.total}</span>
          </div>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          
          {/* Gráfico de Visitas Diarias */}
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100">
            <h3 className="text-lg font-semibold text-civic-ink mb-6">Visitas de los últimos 7 días</h3>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.daily}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f0f0" />
                  <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{fill: '#6b7280', fontSize: 12}} dy={10} />
                  <YAxis axisLine={false} tickLine={false} tick={{fill: '#6b7280', fontSize: 12}} dx={-10} />
                  <Tooltip 
                    contentStyle={{borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)'}}
                  />
                  <Line type="monotone" dataKey="count" stroke="#003897" strokeWidth={3} dot={{r: 4, strokeWidth: 2}} activeDot={{r: 6}} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Gráfico de Rutas Populares */}
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100">
            <h3 className="text-lg font-semibold text-civic-ink mb-6">Rutas más visitadas</h3>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.paths} layout="vertical" margin={{ top: 0, right: 30, left: 40, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f0f0f0" />
                  <XAxis type="number" axisLine={false} tickLine={false} tick={{fill: '#6b7280', fontSize: 12}} />
                  <YAxis type="category" dataKey="path" axisLine={false} tickLine={false} tick={{fill: '#4b5563', fontSize: 12}} width={100} />
                  <Tooltip 
                    cursor={{fill: '#f3f4f6'}}
                    contentStyle={{borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)'}}
                  />
                  <Bar dataKey="count" fill="#CB2C27" radius={[0, 4, 4, 0]} barSize={20} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          
        </div>
      </div>
    </div>
  );
};
