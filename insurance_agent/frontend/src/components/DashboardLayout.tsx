"use client";

import React from 'react';
import Image from 'next/image';
import { usePathname } from 'next/navigation';
import { HeartIcon } from '@heroicons/react/24/outline';

interface DashboardLayoutProps {
    children: React.ReactNode;
}

const DashboardLayout: React.FC<DashboardLayoutProps> = ({ children }) => {
    const pathname = usePathname();

    return (
        <div className="flex h-screen bg-background text-foreground font-sans overflow-hidden">
            {/* Sidebar */}
            <aside className="w-64 bg-secondary border-r border-border flex flex-col shrink-0">
                <div className="p-6 border-b border-border flex items-center justify-center">
                    <div className="relative w-32 h-12">
                        <Image
                            src="/Ema-full-logo-color.webp"
                            alt="EMA Logo"
                            fill
                            className="object-contain"
                            priority
                        />
                    </div>
                </div>

                <nav className="flex-1 p-4 space-y-2 overflow-y-auto">
                    <a
                        href="/"
                        data-active={pathname === '/'}
                        className="flex items-center gap-3 px-4 py-3 rounded-lg text-muted hover:bg-slate-100 hover:text-foreground transition-all data-[active=true]:bg-accent/10 data-[active=true]:text-accent data-[active=true]:font-medium data-[active=true]:border data-[active=true]:border-accent/20 border border-transparent"
                    >
                        <HeartIcon className="w-5 h-5" />
                        Health Claims
                    </a>
                </nav>

                <div className="p-4 border-t border-border">
                    <div className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-100 cursor-pointer transition-colors">
                        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-accent to-purple-600 flex items-center justify-center text-white font-bold shadow-lg">
                            JS
                        </div>
                        <div className="overflow-hidden">
                            <p className="text-sm font-medium truncate text-foreground">John Smith</p>
                            <p className="text-xs text-muted truncate">Senior Adjuster</p>
                        </div>
                    </div>
                </div>
            </aside>

            {/* Main Content */}
            <main className="flex-1 flex flex-col min-w-0">
                {/* Header */}
                <header className="h-16 bg-white/80 backdrop-blur-md border-b border-border flex items-center justify-between px-6 sticky top-0 z-10">
                    <div className="flex items-center gap-4">
                        <h2 className="text-lg font-semibold text-foreground">Health Claims</h2>
                    </div>
                    <div className="flex items-center gap-4">
                    </div>
                </header>

                {/* Content Body */}
                <div className="flex-1 overflow-auto p-6 bg-background relative">
                    {children}
                </div>
            </main>
        </div>
    );
};

export default DashboardLayout;
