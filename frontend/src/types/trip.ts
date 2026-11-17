export type PlaceVerification = {
  status: "verified" | "needs_check" | "unavailable";
  source: string;
  checked_at: string;
  opening_hours: boolean;
};

export type Place = {
  id: string;
  name: string;
  address: string;
  location: string;
  opentime: string;
  cost: string;
  source_time: string;
  city?: string;
  photos?: {title:string;url:string}[];
  unavailable?: boolean;
  /** 地点/营业时间核验结果；旧接口没有该字段时由前端按 opentime 派生。 */
  verification?: PlaceVerification | null;
  distance?: number | null;
};
export type Stop = { place: Place; duration: number; reason: string; activity?: string; fixed_time?: string | null; fixed_next_day?: boolean };
export type Route = {
  origin: string;
  destination: string;
  mode: string;
  duration: number | null;
  distance?: number | null;
  polyline: number[][][];
  source_time: string;
};
export type Day = { stops: Stop[]; routes: Route[]; start_time?: string | null; end_time?: string | null };
export type PlanRequest = {
  city: string;
  days: number;
  start_date: string | null;
  travelers: number;
  interests: string;
  pace: string;
  budget: string;
  must_visit: string;
  transport: string;
};
export type Trip = {
  id: number;
  version?: number;
  title?: string | null;
  request: PlanRequest;
  days: Day[];
  backlog?: Stop[];
  conversation?: ChatMessage[];
  /** 仅预览/新建保存路径回传；GET /api/trips/{id} 的 _detail 不含此字段。 */
  created_at?: string;
  place_notice?: string;
  is_public?: boolean;
  is_owner?: boolean;
  /** 最近一次保存的人与时间（ISO/UTC）；用于冲突弹层说明线上版本来源。 */
  last_edited_by?: string | null;
  last_edited_at?: string | null;
};
export type TripSummary = { id: number; city: string; title?: string | null; request: PlanRequest; /** 一起协作的人数（不含创建者）；GET /api/trips 下发，删除确认据此提示影响范围。 */ collaborator_count?: number };
export type DeletedTrip = { id: number; city: string; title?: string | null; deleted_at: string };
export type ChatMessage = { role: "user" | "assistant"; content: string };

export type TripMapView = { tripId:number; previewKey?:string; days:Day[]; backlog:Stop[]; showBacklog:boolean; focusPlace:Place|null };

export type GuideOutlineDay = {summary:string;stops:{name:string;why:string;place:Place|null;matches:Place[]}[]};
export type PlazaTrip = {id:number;title:string|null;city:string;days:number;owner:string;start_date:string|null};
export type Collaborator = {user_id:number;username:string;role:string};
export type SharedTripSummary = {id:number;title:string|null;city:string;role:string;/** 创建者用户名（GET /api/trips/shared 下发）。 */owner?:string;/** 创建者 + 协作者总人数。 */member_count?:number;/** 此刻在实时房间里的人数，0 表示没人在线。 */online?:number;is_owner?:boolean;is_public?:boolean};
