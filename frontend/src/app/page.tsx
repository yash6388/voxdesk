import { BackendStatus } from "@/components/BackendStatus";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 px-4">
      <h1 className="text-4xl font-bold">VoxDesk</h1>
      <p className="text-lg text-gray-600 dark:text-gray-300">
        Multi-agent voice AI platform for businesses — answers questions from your
        documents and books appointments, by voice or chat.
      </p>
      <BackendStatus />
    </main>
  );
}
