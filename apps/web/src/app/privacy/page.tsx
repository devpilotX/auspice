import { PublishedPage, publishedMetadata } from "@/components/published-page";

export const generateMetadata = () => publishedMetadata("privacy");

export default function Page() {
  return <PublishedPage slug="privacy" />;
}
