import AccountList from "@/components/AccountList";
import SystemStatusPanel from "@/components/SystemStatusPanel";

export default function Home() {
  return (
    <div className="flex flex-col gap-8">
      <section>
        <h1 className="mb-3 text-lg font-semibold">System status</h1>
        <SystemStatusPanel />
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Accounts</h2>
        <AccountList />
      </section>
    </div>
  );
}
