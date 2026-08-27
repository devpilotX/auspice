import { PublishedPage, publishedMetadata } from "@/components/published-page";

export const generateMetadata = () => publishedMetadata("data-sources");

export default function Page() {
  return <PublishedPage slug="data-sources" />;
}
