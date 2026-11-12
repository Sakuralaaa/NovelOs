/** 统一图标出口：Phosphor 线稿（regular 1px 细线），沿用旧的 lucide 名字，页面代码不用改。 */
import { forwardRef } from 'react'
import type { Icon as PhIcon, IconProps } from '@phosphor-icons/react'
import {
  ArrowClockwiseIcon,
  BrainIcon,
  ChatsCircleIcon,
  PaperPlaneTiltIcon,
  RobotIcon,
  StopIcon,
  WrenchIcon,
  ArrowCounterClockwiseIcon,
  ArrowDownIcon,
  ArrowElbowDownLeftIcon,
  ArrowElbowDownRightIcon,
  ArrowRightIcon,
  ArrowUUpLeftIcon,
  ArrowUpIcon,
  ArrowUpRightIcon,
  ArrowsClockwiseIcon,
  ArrowsInLineVerticalIcon,
  ArrowsLeftRightIcon,
  ArrowsOutLineVerticalIcon,
  BookBookmarkIcon,
  BookOpenIcon,
  BookOpenTextIcon,
  BroadcastIcon,
  CaretDownIcon,
  CaretLeftIcon,
  CaretRightIcon,
  CaretUpDownIcon,
  ChatTeardropTextIcon,
  CheckCircleIcon,
  CheckIcon,
  ChecksIcon,
  CircleDashedIcon,
  CircleNotchIcon,
  ClipboardTextIcon,
  CloudArrowUpIcon,
  CloudCheckIcon,
  CopyIcon,
  DiamondIcon,
  DotsThreeIcon,
  DownloadSimpleIcon,
  EyeIcon,
  EyeSlashIcon,
  FeatherIcon,
  FileTextIcon,
  FlagIcon,
  FloppyDiskIcon,
  GearSixIcon,
  GlobeIcon,
  GraphIcon,
  GridFourIcon,
  HighlighterCircleIcon,
  HouseIcon,
  ImageSquareIcon,
  InfoIcon,
  KeyIcon,
  LightbulbIcon,
  LightningIcon,
  ListIcon,
  LockKeyIcon,
  MagicWandIcon,
  MagnifyingGlassIcon,
  MapPinIcon,
  MoonIcon,
  PackageIcon,
  PathIcon,
  PenNibIcon,
  PencilSimpleIcon,
  PlantIcon,
  PlugIcon,
  PlusIcon,
  QuotesIcon,
  RadioButtonIcon,
  RowsIcon,
  ShieldCheckIcon,
  ShieldIcon,
  SidebarIcon,
  SidebarSimpleIcon,
  SignOutIcon,
  SparkleIcon,
  SquaresFourIcon,
  StackIcon,
  StackSimpleIcon,
  StarFourIcon,
  SunIcon,
  TagIcon,
  TextTIcon,
  TrashIcon,
  TrashSimpleIcon,
  TreeStructureIcon,
  UserIcon,
  UserPlusIcon,
  WarningCircleIcon,
  WarningIcon,
  XCircleIcon,
  XIcon,
} from '@phosphor-icons/react'

export type IconCmp = PhIcon
type Props = IconProps & { strokeWidth?: number | string }

function wrap(C: PhIcon, name: string) {
  const W = forwardRef<SVGSVGElement, Props>(({ strokeWidth, weight, ...p }, ref) => (
    <C ref={ref} weight={weight ?? (Number(strokeWidth) >= 2.2 ? 'bold' : 'regular')} {...p} />
  ))
  W.displayName = name
  return W as unknown as PhIcon
}

export const AlertCircle = wrap(WarningCircleIcon, 'AlertCircle')
export const AlertTriangle = wrap(WarningIcon, 'AlertTriangle')
export const ArrowDown = wrap(ArrowDownIcon, 'ArrowDown')
export const ArrowRight = wrap(ArrowRightIcon, 'ArrowRight')
export const ArrowRightLeft = wrap(ArrowsLeftRightIcon, 'ArrowRightLeft')
export const ArrowUp = wrap(ArrowUpIcon, 'ArrowUp')
export const ArrowUpRight = wrap(ArrowUpRightIcon, 'ArrowUpRight')
export const BookOpen = wrap(BookOpenIcon, 'BookOpen')
export const BookOpenCheck = wrap(BookOpenTextIcon, 'BookOpenCheck')
export const BookPlus = wrap(BookBookmarkIcon, 'BookPlus')
export const Check = wrap(CheckIcon, 'Check')
export const CheckCheck = wrap(ChecksIcon, 'CheckCheck')
export const CheckCircle2 = wrap(CheckCircleIcon, 'CheckCircle2')
export const ChevronDown = wrap(CaretDownIcon, 'ChevronDown')
export const ChevronLeft = wrap(CaretLeftIcon, 'ChevronLeft')
export const ChevronRight = wrap(CaretRightIcon, 'ChevronRight')
export const ChevronsDownUp = wrap(ArrowsInLineVerticalIcon, 'ChevronsDownUp')
export const ChevronsUpDown = wrap(CaretUpDownIcon, 'ChevronsUpDown')
export const CircleDashed = wrap(CircleDashedIcon, 'CircleDashed')
export const CircleDot = wrap(RadioButtonIcon, 'CircleDot')
export const ClipboardPaste = wrap(ClipboardTextIcon, 'ClipboardPaste')
export const CloudCheck = wrap(CloudCheckIcon, 'CloudCheck')
export const CloudUpload = wrap(CloudArrowUpIcon, 'CloudUpload')
export const Copy = wrap(CopyIcon, 'Copy')
export const CornerDownLeft = wrap(ArrowElbowDownLeftIcon, 'CornerDownLeft')
export const CornerDownRight = wrap(ArrowElbowDownRightIcon, 'CornerDownRight')
export const Download = wrap(DownloadSimpleIcon, 'Download')
export const Eye = wrap(EyeIcon, 'Eye')
export const EyeOff = wrap(EyeSlashIcon, 'EyeOff')
export const Feather = wrap(FeatherIcon, 'Feather')
export const FileText = wrap(FileTextIcon, 'FileText')
export const Flag = wrap(FlagIcon, 'Flag')
export const Gem = wrap(DiamondIcon, 'Gem')
export const Globe2 = wrap(GlobeIcon, 'Globe2')
export const Highlighter = wrap(HighlighterCircleIcon, 'Highlighter')
export const Home = wrap(HouseIcon, 'Home')
export const House = wrap(HouseIcon, 'House')
export const ImagePlus = wrap(ImageSquareIcon, 'ImagePlus')
export const Info = wrap(InfoIcon, 'Info')
export const KeyRound = wrap(KeyIcon, 'KeyRound')
export const Layers = wrap(StackIcon, 'Layers')
export const Layers3 = wrap(StackSimpleIcon, 'Layers3')
export const LayoutDashboard = wrap(SquaresFourIcon, 'LayoutDashboard')
export const LayoutGrid = wrap(GridFourIcon, 'LayoutGrid')
export const Lightbulb = wrap(LightbulbIcon, 'Lightbulb')
export const ListTree = wrap(TreeStructureIcon, 'ListTree')
export const Loader2 = wrap(CircleNotchIcon, 'Loader2')
export const LockKeyhole = wrap(LockKeyIcon, 'LockKeyhole')
export const LogOut = wrap(SignOutIcon, 'LogOut')
export const MapPin = wrap(MapPinIcon, 'MapPin')
export const Menu = wrap(ListIcon, 'Menu')
export const MessageSquareQuote = wrap(ChatTeardropTextIcon, 'MessageSquareQuote')
export const Moon = wrap(MoonIcon, 'Moon')
export const MoreHorizontal = wrap(DotsThreeIcon, 'MoreHorizontal')
export const Package = wrap(PackageIcon, 'Package')
export const PanelLeftClose = wrap(SidebarSimpleIcon, 'PanelLeftClose')
export const PanelLeftOpen = wrap(SidebarSimpleIcon, 'PanelLeftOpen')
export const PanelRightClose = wrap(SidebarIcon, 'PanelRightClose')
export const PanelRightOpen = wrap(SidebarIcon, 'PanelRightOpen')
export const PenLine = wrap(PenNibIcon, 'PenLine')
export const Pencil = wrap(PencilSimpleIcon, 'Pencil')
export const Plug = wrap(PlugIcon, 'Plug')
export const Plus = wrap(PlusIcon, 'Plus')
export const Quote = wrap(QuotesIcon, 'Quote')
export const Radar = wrap(BroadcastIcon, 'Radar')
export const RefreshCw = wrap(ArrowsClockwiseIcon, 'RefreshCw')
export const RotateCcw = wrap(ArrowCounterClockwiseIcon, 'RotateCcw')
export const RotateCw = wrap(ArrowClockwiseIcon, 'RotateCw')
export const Route = wrap(PathIcon, 'Route')
export const Rows3 = wrap(RowsIcon, 'Rows3')
export const Save = wrap(FloppyDiskIcon, 'Save')
export const Search = wrap(MagnifyingGlassIcon, 'Search')
export const Settings = wrap(GearSixIcon, 'Settings')
export const Shield = wrap(ShieldIcon, 'Shield')
export const ShieldCheck = wrap(ShieldCheckIcon, 'ShieldCheck')
export const Sparkle = wrap(SparkleIcon, 'Sparkle')
export const Sparkles = wrap(StarFourIcon, 'Sparkles')
export const Sprout = wrap(PlantIcon, 'Sprout')
export const Sun = wrap(SunIcon, 'Sun')
export const Tag = wrap(TagIcon, 'Tag')
export const Trash = wrap(TrashIcon, 'Trash')
export const Trash2 = wrap(TrashSimpleIcon, 'Trash2')
export const Type = wrap(TextTIcon, 'Type')
export const Undo2 = wrap(ArrowUUpLeftIcon, 'Undo2')
export const UnfoldVertical = wrap(ArrowsOutLineVerticalIcon, 'UnfoldVertical')
export const User = wrap(UserIcon, 'User')
export const UserPlus = wrap(UserPlusIcon, 'UserPlus')
export const Wand2 = wrap(MagicWandIcon, 'Wand2')
export const Waypoints = wrap(GraphIcon, 'Waypoints')
export const X = wrap(XIcon, 'X')
export const XCircle = wrap(XCircleIcon, 'XCircle')
export const Zap = wrap(LightningIcon, 'Zap')
export const Bot = wrap(RobotIcon, 'Bot')
export const Brain = wrap(BrainIcon, 'Brain')
export const Chats = wrap(ChatsCircleIcon, 'Chats')
export const Send = wrap(PaperPlaneTiltIcon, 'Send')
export const StopSquare = wrap(StopIcon, 'StopSquare')
export const Wrench = wrap(WrenchIcon, 'Wrench')
