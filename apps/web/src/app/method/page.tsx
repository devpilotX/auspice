import { PublishedPage, publishedMetadata } from "@/components/published-page";

export const generateMetadata = () => publishedMetadata("method");

export default function Page() {
  return <PublishedPage slug="method" />;
}
