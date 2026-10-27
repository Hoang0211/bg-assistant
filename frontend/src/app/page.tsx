import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { HealthStatus } from "@/features/health/health-status";

export default function HomePage() {
  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Board Game Assistant</CardTitle>
          <CardDescription>
            Add your board game rulebooks, then ask questions about the rules.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <HealthStatus />
        </CardContent>
        <CardFooter>
          <Button>Add a game</Button>
        </CardFooter>
      </Card>
    </main>
  );
}
