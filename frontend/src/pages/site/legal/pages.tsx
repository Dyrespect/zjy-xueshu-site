import { LegalPage } from "../LegalPage";
import { DISCLAIMER, PRIVACY, TERMS } from "./docs";

// 协议三页（一个懒加载包，react-markdown 只在这里用）
export const TermsPage = () => <LegalPage doc={TERMS} />;
export const PrivacyPage = () => <LegalPage doc={PRIVACY} />;
export const DisclaimerPage = () => <LegalPage doc={DISCLAIMER} />;
