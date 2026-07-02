import type { ReactNode } from 'react';
import AppBar from './AppBar';
import Sidebar from './Sidebar';
import StatusBar from './StatusBar';

interface AppShellProps {
  crumbs: string[];
  children: ReactNode;
  statusItems?: string[];
  licitacionCount?: number;
  queueCount?: number;
}

export default function AppShell({
  crumbs,
  children,
  statusItems,
  licitacionCount,
  queueCount,
}: AppShellProps) {
  return (
    <div className="flex flex-col h-screen bg-bg overflow-hidden">
      <AppBar crumbs={crumbs} />
      <div className="flex flex-1 min-h-0">
        <Sidebar licitacionCount={licitacionCount} queueCount={queueCount} />
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
          {children}
        </div>
      </div>
      <StatusBar items={statusItems} />
    </div>
  );
}
