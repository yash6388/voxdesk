import { BusinessList } from "@/components/BusinessList";

export default function Home() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Your businesses</h1>
        <p className="mt-1 text-zinc-500">
          Each business gets its own AI assistant that answers from its documents.
        </p>
      </div>
      <BusinessList />
    </div>
  );
}
