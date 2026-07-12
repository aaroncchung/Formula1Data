import { TopBar } from "@/components/app-shell/TopBar";
import { Sidebar } from "@/components/app-shell/Sidebar";
import { APP_NAME } from "@/lib/constants";

type AppShellProps = {
  children: React.ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="min-h-screen">
      <div className="fixed inset-y-0 left-0 z-30 hidden w-[232px] border-r border-line/70 bg-carbon/95 shadow-2xl lg:block">
        <Sidebar />
      </div>
      <div className="lg:pl-[232px]">
        <TopBar />
        <main className="mx-auto w-full max-w-[1680px] px-4 pb-12 pt-6 sm:px-6 lg:px-8">
          {children}
        </main>
        <footer className="border-t border-line/60 px-4 py-5 text-center text-xs text-slate-600">
          {APP_NAME} · Personal, unofficial Formula 1 analytics.
        </footer>
      </div>
    </div>
  );
}

