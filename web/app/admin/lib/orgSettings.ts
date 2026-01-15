export type BusinessHourWindow = {
  enabled: boolean;
  start: string;
  end: string;
};

export type OrgSettingsResponse = {
  org_id: string;
  timezone: string;
  currency: "CAD" | "USD";
  language: "en" | "ru";
  business_hours: Record<string, BusinessHourWindow>;
  holidays: string[];
  legal_name?: string | null;
  legal_bn?: string | null;
  legal_gst_hst?: string | null;
  legal_address?: string | null;
  legal_phone?: string | null;
  legal_email?: string | null;
  legal_website?: string | null;
  branding: Record<string, string>;
};

export const DEFAULT_ORG_TIMEZONE = "America/Edmonton";
