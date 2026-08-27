import { PublishedPage, publishedMetadata } from "@/components/published-page";

export const generateMetadata = () => publishedMetadata("terms");

export default function Page() {
  return <PublishedPage slug="terms" />;
}
