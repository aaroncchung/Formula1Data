import { TopBar } from "@/components/app-shell/TopBar";
import { Sidebar } from "@/components/app-shell/Sidebar";
import { APP_NAME } from "@/lib/constants";

type AppShellProps = {
  children: React.ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="min-h-screen">
      <div className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-line/80 bg-carbon/95 lg:block">
        <Sidebar />
      </div>
      <div className="lg:pl-64">
        <TopBar />
        <main className="mx-auto w-full max-w-[1600px] px-4 pb-10 pt-5 sm:px-6 lg:px-8">
          {children}
        </main>
        <footer className="border-t border-line/70 px-4 py-5 text-center text-xs text-slate-500 lg:pl-64">
          {APP_NAME} - Unofficial personal analytics dashboard.
        </footer>
      </div>
    </div>
  );
}

