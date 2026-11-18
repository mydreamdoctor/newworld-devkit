/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * For complete copyright and license terms please see the LICENSE at the root of this distribution.
 *
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 *
 */

#pragma once

#include <GradientSignal/Editor/EditorGradientComponentBase.h>
#include <NWCapital/Components/CapitalCookieGradientComponent.h>

namespace NWCapital
{
    class EditorCapitalCookieGradientComponent
        : public GradientSignal::EditorGradientComponentBase<CapitalCookieGradientComponent, CapitalCookieGradientConfig>
    {
    public:
        using BaseClassType = GradientSignal::EditorGradientComponentBase<CapitalCookieGradientComponent, CapitalCookieGradientConfig>;
        AZ_EDITOR_COMPONENT(EditorCapitalCookieGradientComponent, "{5D1A8E3B-4F6C-4A9D-8E2B-7C3F5A1D6E04}", BaseClassType);
        static void Reflect(AZ::ReflectContext* context);

        static constexpr const char* const s_categoryName = "Gradient Modifiers";
        static constexpr const char* const s_componentName = "NW Capital Cookie Gradient Modifier";
        static constexpr const char* const s_componentDescription =
            "Applies New World capital 'cookie' terrain stamps (flatten + blend ring) over a source heightmap gradient";
        static constexpr const char* const s_icon = "Editor/Icons/Components/GradientModifier.svg";
        static constexpr const char* const s_viewportIcon = "Editor/Icons/Components/Viewport/GradientModifier.svg";
        static constexpr const char* const s_helpUrl = "";
    };
}
