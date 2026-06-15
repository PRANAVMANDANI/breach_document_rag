import React from 'react';
import { Cpu, Sun, Moon } from 'lucide-react';

export default function Navbar({ connectionStatus, theme, setTheme }) {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-claude-border/80 bg-claude-bg/85 backdrop-blur-md transition-colors duration-300">
      <div className="mx-auto flex max-w-7xl h-16 items-center justify-between px-4 sm:px-6 lg:px-8">
        
        {/* Brand Logo */}
        <div className="flex items-center space-x-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-claude-accent text-white shadow-md shadow-claude-accent/10">
            <Cpu className="h-5 w-5 animate-pulse-slow text-white" />
          </div>
          <div>
            <h1 className="font-outfit text-xl font-bold tracking-tight text-claude-text-primary">
              Legal<span className="text-claude-accent font-extrabold">Eagle</span>
            </h1>
            <p className="text-[10px] text-claude-text-secondary font-mono tracking-widest uppercase">Contract Risk Agent</p>
          </div>
        </div>

        {/* Navigation, Theme Switcher and System Badges */}
        <div className="flex items-center space-x-3">
          {/* Connection status */}
          <div className="flex items-center space-x-2 bg-claude-sidebar/60 px-3 py-1.5 rounded-full border border-claude-border transition-colors duration-300">
            <span className={`h-2.5 w-2.5 rounded-full ${
              connectionStatus === 'connected' 
                ? 'bg-emerald-500 shadow-emerald-500/30' 
                : connectionStatus === 'checking' 
                  ? 'bg-amber-500 animate-pulse' 
                  : 'bg-rose-500 shadow-rose-500/30'
              } shadow-sm`} 
            />
            <span className="text-[11px] font-medium text-claude-text-secondary hidden sm:inline">
              {connectionStatus === 'connected' ? 'API Connected' : connectionStatus === 'checking' ? 'Connecting...' : 'API Disconnected'}
            </span>
          </div>

          {/* Theme switcher */}
          <button
            onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
            className="p-1.5 rounded-xl border border-claude-border bg-claude-sidebar/60 text-claude-text-secondary hover:text-claude-text-primary hover:bg-claude-border/50 cursor-pointer transition-all duration-200"
            title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
          >
            {theme === 'light' ? (
              <Moon className="h-4.5 w-4.5" />
            ) : (
              <Sun className="h-4.5 w-4.5" />
            )}
          </button>
        </div>

      </div>
    </header>
  );
}
