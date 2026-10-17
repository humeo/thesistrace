import { i18n } from "./index";
import { billingEn, billingZh } from "./messages/billing";

// Loaded with billing and tracking routes, before either renders its messages.
i18n.addResourceBundle("en", "billing", billingEn);
i18n.addResourceBundle("zh-CN", "billing", billingZh);
