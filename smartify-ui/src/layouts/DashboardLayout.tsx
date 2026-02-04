import { Outlet } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/TopBar";

const DashboardLayout = () => {
  return (
    <div className="min-h-screen text-foreground">
      <div className="flex">
        <Sidebar />

        <div className="flex-1 min-w-0">
          <TopBar />
          <main className="p-6 md:p-10">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
};

export default DashboardLayout;
